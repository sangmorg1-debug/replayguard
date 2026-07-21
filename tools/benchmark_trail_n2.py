"""Benchmark ReplayGuard failure localization on a fetched public TRAIL slice."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from pathlib import Path

from replayguard.diagnosis import diagnose, load_ground_truth, normalize_category, score_diagnosis
from replayguard.otel import import_traces

EXECUTION_CATEGORIES = {"Tool Definition Issues", "Environment Setup Errors", "Rate Limiting",
                        "Authentication Errors", "Service Errors", "Resource Not Found",
                        "Resource Exhaustion", "Timeout Issues", "Context Handling Failures", "Resource Abuse"}


def wilson(successes: int, total: int, z: float = 1.96) -> list[float]:
    if not total:
        return [0.0, 0.0]
    p = successes / total; denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - spread), min(1.0, center + spread)]


def bootstrap_mean(values: list[float], samples: int = 10_000) -> list[float]:
    if not values:
        return [0.0, 0.0]
    generator = random.Random(20260719); size = len(values)
    means = sorted(sum(generator.choice(values) for _ in range(size)) / size for _ in range(samples))
    return [means[int(samples * .025)], means[int(samples * .975)]]


def aggregate(rows: list[dict]) -> dict:
    expected = sum(row["expected_pairs"] for row in rows)
    predicted = sum(row["predicted_pairs"] for row in rows)
    matched = sum(row["matched_pairs"] for row in rows)
    precision = matched / predicted if predicted else 0.0
    recall = matched / expected if expected else 0.0
    per_trace = [row["location_category_joint_accuracy"] for row in rows]
    return {"traces": len(rows), "expected_pairs": expected, "predicted_pairs": predicted,
            "matched_pairs": matched, "pair_precision": precision, "micro_pair_recall": recall,
            "pair_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "macro_joint_span_category_accuracy": sum(per_trace) / len(per_trace) if per_trace else 0.0,
            "macro_95pct_trace_bootstrap": bootstrap_mean(per_trace)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=".verify/upstream/trail-n2")
    parser.add_argument("--output", default=".verify/reports/trail-n2.json")
    args = parser.parse_args(argv)
    root = Path(args.corpus); manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    rows = []; all_expected = all_predicted = all_matched = 0
    subset_expected = subset_matched = 0
    for record in manifest["records"]:
        trace = json.loads((root / record["trace_path"]).read_text(encoding="utf-8"))
        truth = load_ground_truth(root / record["annotation_path"])
        diagnosis = diagnose(import_traces(trace)[0]); score = score_diagnosis(diagnosis, truth)
        expected_subset = {(str(item.get("location")), normalize_category(item.get("category"))) for item in truth.get("errors", [])
                           if normalize_category(item.get("category")) in EXECUTION_CATEGORIES}
        predicted = {(item.span_id, item.category) for item in diagnosis.suspects}
        partition = "calibration" if int(hashlib.sha256(record["trace_id"].encode()).hexdigest()[:8], 16) % 5 == 0 else "holdout"
        score.update({"split": record["split"], "partition": partition, "execution_expected_pairs": len(expected_subset),
                      "execution_matched_pairs": len(expected_subset & predicted)})
        rows.append(score); all_expected += score["expected_pairs"]; all_predicted += score["predicted_pairs"]
        all_matched += score["matched_pairs"]; subset_expected += len(expected_subset); subset_matched += len(expected_subset & predicted)
    precision = all_matched / all_predicted if all_predicted else 0.0
    recall = all_matched / all_expected if all_expected else 0.0
    per_trace = [row["location_category_joint_accuracy"] for row in rows]
    official_joint = sum(per_trace) / len(per_trace) if per_trace else 0.0
    report = {"benchmark": "TRAIL pinned corpus", "revision": manifest["revision"],
              "selection": manifest.get("selection", "all 148 gated trace/annotation pairs at the pinned revision"),
              "candidate_limit": 3, "partition_rule": "calibration iff uint32(sha256(trace_id)[:8]) mod 5 == 0; otherwise holdout",
              "traces": len(rows),
              "all_categories": {"expected_pairs": all_expected, "predicted_pairs": all_predicted,
                 "matched_pairs": all_matched, "official_macro_joint_span_category_accuracy": official_joint,
                 "official_macro_95pct_trace_bootstrap": bootstrap_mean(per_trace),
                 "micro_pair_recall": recall, "micro_recall_95pct_wilson": wilson(all_matched, all_expected),
                 "pair_precision": precision, "pair_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0},
              "deterministic_execution_api_subset": {"expected_pairs": subset_expected, "matched_pairs": subset_matched,
                 "joint_span_category_accuracy": subset_matched / subset_expected if subset_expected else 0.0,
                 "joint_accuracy_95pct_wilson": wilson(subset_matched, subset_expected)},
              "evaluation_partitions": {
                  "calibration": aggregate([row for row in rows if row["partition"] == "calibration"]),
                  "holdout": aggregate([row for row in rows if row["partition"] == "holdout"]),
              }, "traces_detail": rows}
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(target.resolve()), **{k: report[k] for k in ("traces", "all_categories", "deterministic_execution_api_subset")}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
