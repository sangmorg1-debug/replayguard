"""Pre-registered calibration/holdout gate for a TRAIL-safe diagnostic router."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from replayguard.routing_gate import select_routing_policy
from experiment_meta_ranker import fit, load_cases, metrics, predict

SPLIT_SALT = "replayguard-trail-safe-router-v1"


def partition(identifier: str) -> str:
    """Freeze 40% of TRAIL traces for calibration and 60% for one-shot holdout."""
    value = int(hashlib.sha256(f"{SPLIT_SALT}:{identifier}".encode()).hexdigest()[:8], 16) % 10
    return "calibration" if value < 4 else "holdout"


def inner_fold(identifier: str) -> int:
    return int(hashlib.sha256(f"{SPLIT_SALT}:inner:{identifier}".encode()).hexdigest()[:8], 16) % 5


def claim_predictions(cases):
    return {(case["dataset"], case["id"]): set(case["signals"]["claim_graph"]) for case in cases}


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--trail", default=".verify/upstream/trail-n2")
    parser.add_argument("--external", default=".verify/upstream/diagnostic-corpora")
    parser.add_argument("--output", default=".verify/reports/trail-safe-router.json")
    parser.add_argument("--minimum-f1-gain", type=float, default=.01); args = parser.parse_args(argv)
    cases = load_cases(Path(args.trail), Path(args.external))
    external = [case for case in cases if case["dataset"] != "trail"]
    trail = [case for case in cases if case["dataset"] == "trail"]
    calibration = [case for case in trail if partition(case["id"]) == "calibration"]
    holdout = [case for case in trail if partition(case["id"]) == "holdout"]

    calibration_meta = {}
    for held in range(5):
        train = external + [case for case in calibration if inner_fold(case["id"]) != held]
        test = [case for case in calibration if inner_fold(case["id"]) == held]
        calibration_meta.update(predict(fit(train), test))
    calibration_claim = metrics(calibration, claim_predictions(calibration))
    calibration_challenger = metrics(calibration, calibration_meta)
    decision = select_routing_policy(calibration_claim, calibration_challenger,
                                     minimum_f1_gain=args.minimum_f1_gain)

    # The choice above is frozen before this one-shot holdout fit and evaluation.
    holdout_meta = predict(fit(external + calibration), holdout)
    holdout_claim = metrics(holdout, claim_predictions(holdout))
    holdout_challenger = metrics(holdout, holdout_meta)
    selected_predictions = holdout_meta if decision.policy == "meta_ranker" else claim_predictions(holdout)
    selected = metrics(holdout, selected_predictions)
    report = {
        "protocol": {"split_salt": SPLIT_SALT, "calibration_fraction_rule": "sha256 bucket 0-3 of 10",
                     "holdout_fraction_rule": "sha256 bucket 4-9 of 10", "minimum_f1_gain": args.minimum_f1_gain,
                     "precision_regression_allowed": False, "candidate_limit": 3},
        "counts": {"calibration": len(calibration), "holdout": len(holdout), "external_training": len(external)},
        "calibration": {"fallback_claim_graph": calibration_claim, "challenger_meta_ranker": calibration_challenger},
        "frozen_decision": asdict(decision),
        "holdout": {"selected": selected, "fallback_claim_graph": holdout_claim,
                    "challenger_meta_ranker_counterfactual": holdout_challenger},
        "warning": "Location-only. The counterfactual is reported for audit and did not influence the frozen choice."}
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8"); print(json.dumps(report, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
