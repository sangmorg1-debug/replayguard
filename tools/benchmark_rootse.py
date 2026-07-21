"""Untuned external validation on the pinned public RootSE corpus."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from replayguard.diagnostic_corpora import ROOTSE_REVISION, load_rootse, localization_metrics
try:
    from experiment_meta_ranker import baseline, fit, load_cases, make_case, predict, signal_metrics, step_run
except ModuleNotFoundError:
    from tools.experiment_meta_ranker import baseline, fit, load_cases, make_case, predict, signal_metrics, step_run
from replayguard.invariants import inspect_semantic_spans


def revision(root: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--rootse", default=".verify/upstream/rootse")
    parser.add_argument("--trail", default=".verify/upstream/trail-n2")
    parser.add_argument("--external", default=".verify/upstream/diagnostic-corpora")
    parser.add_argument("--output", default=".verify/reports/rootse-external.json"); args = parser.parse_args(argv)
    root = Path(args.rootse); actual_revision = revision(root)
    if actual_revision != ROOTSE_REVISION: raise SystemExit(f"RootSE revision mismatch: {actual_revision}")
    training = load_cases(Path(args.trail), Path(args.external)); rootse = []
    metadata = {}
    for row in load_rootse(root):
        steps = [(step["id"], step["raw"]) for step in row["input"]["steps"]]
        raw = [{"id": location, "role": "assistant", "content": content} for location, content in steps]
        run = step_run("rootse:" + row["id"], raw)
        case = make_case("rootse", row["id"], steps, row["gold"], baseline(run),
                         inspect_semantic_spans([{"id": a, "raw": b} for a, b in steps]))
        rootse.append(case); metadata[row["id"]] = row["meta"]
    if len(metadata) != len(rootse): raise SystemExit("RootSE trajectory IDs are not unique")
    model_predictions = predict(fit(training), rootse)
    def score_predictions(predictions):
        rows = []
        for case in rootse:
            candidates = predictions[("rootse", case["id"])]
            # Sets lose order, so top-one is available only for standalone ordered signals below.
            rows.append((case["expected"], candidates))
        return localization_metrics(rows)
    agent_counts = {}; model_counts = {}
    for value in metadata.values():
        agent_counts[value["agent"]] = agent_counts.get(value["agent"], 0) + 1
        model_counts[value["model"]] = model_counts.get(value["model"], 0) + 1
    expected = sum(len(case["expected"]) for case in rootse)
    report = {"dataset": "dengdan1999/RootSE", "revision": actual_revision, "license": "mit",
              "cases": len(rootse), "gold_locations": expected, "agents": agent_counts, "models": model_counts,
              "candidate_limit": 3, "training_rootse_examples": 0,
              "baseline": signal_metrics(rootse, "baseline"), "invariants": signal_metrics(rootse, "invariants"),
              "claim_graph": signal_metrics(rootse, "claim_graph"),
              "hypotheses_top8": signal_metrics(rootse, "hypotheses"),
              "candidate_union_oracle_recall": sum(len(case["expected"] & set().union(*case["signals"].values())) for case in rootse) / expected,
              "meta_ranker_leave_rootse_out": score_predictions(model_predictions),
              "warning": "RootSE has one earliest-error label per trace; this is location-only and was not used for training or selection."}
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8"); print(json.dumps(report, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
