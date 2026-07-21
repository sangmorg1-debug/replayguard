"""Repeated nested cross-validation for TRAIL router-selection stability."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

from replayguard.routing_gate import select_routing_policy
try:
    from experiment_meta_ranker import fit, load_cases, metrics, predict
except ModuleNotFoundError:  # Imported as tools.experiment_nested_router by tests.
    from tools.experiment_meta_ranker import fit, load_cases, metrics, predict

PROTOCOL = "replayguard-nested-router-v1"


def fold(identifier: str, repeat: int, level: str, folds: int = 5) -> int:
    value = hashlib.sha256(f"{PROTOCOL}:{repeat}:{level}:{identifier}".encode()).hexdigest()[:8]
    return int(value, 16) % folds


def claim_predictions(cases):
    return {(case["dataset"], case["id"]): set(case["signals"]["claim_graph"]) for case in cases}


def paired_bootstrap(cases, fallback, challenger, *, samples=10000, seed=20260720):
    """Bootstrap complete traces and return the paired micro-F1 delta interval."""
    rng = np.random.default_rng(seed); size = len(cases); deltas = np.empty(samples)
    def counts(indices, predictions):
        expected = predicted = matched = 0
        for index in indices:
            case = cases[int(index)]; guess = predictions[(case["dataset"], case["id"])]
            expected += len(case["expected"]); predicted += len(guess); matched += len(case["expected"] & guess)
        return expected, predicted, matched
    def f1(values):
        expected, predicted, matched = values
        return 2 * matched / (expected + predicted) if expected + predicted else 0.0
    for sample in range(samples):
        indices = rng.integers(0, size, size=size)
        deltas[sample] = f1(counts(indices, challenger)) - f1(counts(indices, fallback))
    return {"samples": samples, "mean_f1_delta": float(deltas.mean()),
            "ci95_low": float(np.quantile(deltas, .025)), "ci95_high": float(np.quantile(deltas, .975)),
            "probability_delta_gt_zero": float(np.mean(deltas > 0))}


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--trail", default=".verify/upstream/trail-n2")
    parser.add_argument("--external", default=".verify/upstream/diagnostic-corpora")
    parser.add_argument("--output", default=".verify/reports/nested-router.json")
    parser.add_argument("--repeats", type=int, default=5); parser.add_argument("--minimum-f1-gain", type=float, default=.01)
    args = parser.parse_args(argv)
    if args.repeats < 1: parser.error("--repeats must be positive")
    cases = load_cases(Path(args.trail), Path(args.external))
    external = [case for case in cases if case["dataset"] != "trail"]
    trail = [case for case in cases if case["dataset"] == "trail"]
    repeat_reports = []
    all_selected_rows = []; all_claim_rows = []; all_meta_rows = []; decisions = Counter()
    for repeat in range(args.repeats):
        selected_predictions = {}; meta_predictions = {}; fold_reports = []
        for outer in range(5):
            outer_test = [case for case in trail if fold(case["id"], repeat, "outer") == outer]
            outer_train = [case for case in trail if fold(case["id"], repeat, "outer") != outer]
            calibration_meta = {}
            for inner in range(5):
                inner_test = [case for case in outer_train if fold(case["id"], repeat, f"inner-{outer}") == inner]
                if not inner_test: continue
                inner_train = [case for case in outer_train if fold(case["id"], repeat, f"inner-{outer}") != inner]
                calibration_meta.update(predict(fit(external + inner_train), inner_test))
            fallback_metrics = metrics(outer_train, claim_predictions(outer_train))
            challenger_metrics = metrics(outer_train, calibration_meta)
            decision = select_routing_policy(fallback_metrics, challenger_metrics,
                                             minimum_f1_gain=args.minimum_f1_gain)
            decisions[decision.policy] += 1
            outer_meta = predict(fit(external + outer_train), outer_test)
            meta_predictions.update(outer_meta)
            chosen = outer_meta if decision.policy == "meta_ranker" else claim_predictions(outer_test)
            selected_predictions.update(chosen)
            fold_reports.append({"outer_fold": outer, "test_cases": len(outer_test), "policy": decision.policy,
                                 "calibration_f1_delta": decision.calibration_f1_delta,
                                 "calibration_precision_delta": decision.calibration_precision_delta})
        claim = claim_predictions(trail)
        selected_metric = metrics(trail, selected_predictions); claim_metric = metrics(trail, claim)
        meta_metric = metrics(trail, meta_predictions)
        interval = paired_bootstrap(trail, claim, meta_predictions, seed=20260720 + repeat)
        repeat_reports.append({"repeat": repeat, "selected": selected_metric, "always_claim_graph": claim_metric,
                               "always_meta_ranker": meta_metric, "paired_bootstrap_meta_minus_claim": interval,
                               "folds": fold_reports})
        all_selected_rows.extend((case["expected"], selected_predictions[("trail", case["id"])]) for case in trail)
        all_claim_rows.extend((case["expected"], claim[("trail", case["id"])]) for case in trail)
        all_meta_rows.extend((case["expected"], meta_predictions[("trail", case["id"])]) for case in trail)
    from replayguard.diagnostic_corpora import localization_metrics
    report = {"protocol": {"name": PROTOCOL, "repeats": args.repeats, "outer_folds": 5, "inner_folds": 5,
                           "minimum_f1_gain": args.minimum_f1_gain, "precision_regression_allowed": False},
              "selection_counts": dict(decisions),
              "aggregate": {"selected_router": localization_metrics(all_selected_rows),
                            "always_claim_graph": localization_metrics(all_claim_rows),
                            "always_meta_ranker": localization_metrics(all_meta_rows)},
              "repeats": repeat_reports,
              "bootstrap_summary": {"repeats_with_ci_entirely_above_zero": sum(
                  row["paired_bootstrap_meta_minus_claim"]["ci95_low"] > 0 for row in repeat_reports),
                  "repeats_with_point_estimate_above_zero": sum(
                  row["paired_bootstrap_meta_minus_claim"]["mean_f1_delta"] > 0 for row in repeat_reports)},
              "warning": "Repeated nested-CV estimate, not a new untouched holdout or production headline."}
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8"); print(json.dumps(report, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
