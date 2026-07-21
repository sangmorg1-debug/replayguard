"""Resume-safe evaluation of the optional semantic judge on real RAGTruth test responses."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from replayguard.semantic import LETTUCE_MODEL, LETTUCE_REVISION, LettuceDetectJudge


def rows(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle: yield json.loads(line)


def metrics(records, threshold):
    tp = sum(item["actual"] and item["score"] >= threshold for item in records)
    fp = sum(not item["actual"] and item["score"] >= threshold for item in records)
    fn = sum(item["actual"] and item["score"] < threshold for item in records)
    tn = sum(not item["actual"] and item["score"] < threshold for item in records)
    precision = tp / (tp + fp) if tp + fp else 0; recall = tp / (tp + fn) if tp + fn else 0
    return {"records": len(records), "threshold": threshold, "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "precision": precision, "recall": recall, "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
            "accuracy": (tp + tn) / len(records) if records else 0}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=".verify/upstream/ragtruth")
    parser.add_argument("--checkpoint", help="prediction JSONL (default is isolated by threshold)")
    parser.add_argument("--output", default=".verify/reports/ragtruth-semantic.json")
    parser.add_argument("--threshold", type=float, default=.5)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--balanced-per-class", type=int, help="deterministic timing/calibration slice")
    parser.add_argument("--balanced-per-task-class", type=int, help="stratified records per label for each task")
    parser.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args(argv)
    root = Path(args.corpus)
    checkpoint = Path(args.checkpoint or f".verify/reports/ragtruth-lettuce-base-v1-t{args.threshold:g}-predictions.jsonl")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    sources = {item["source_id"]: item for item in rows(root / "source_info.jsonl")}
    selected = [item for item in rows(root / "response.jsonl") if item.get("split") == "test" and item.get("quality") == "good"]
    if args.balanced_per_class:
        positive = [item for item in selected if item.get("labels")][:args.balanced_per_class]
        negative = [item for item in selected if not item.get("labels")][:args.balanced_per_class]
        selected = positive + negative
    if args.balanced_per_task_class:
        selected = [item for task in ("Summary", "QA", "Data2txt")
                    for label in (True, False)
                    for item in [row for row in selected
                                 if bool(row.get("labels")) is label and sources[row["source_id"]].get("task_type") == task][:args.balanced_per_task_class]]
    if args.limit: selected = selected[:args.limit]
    completed = {item["id"]: item for item in rows(checkpoint)} if checkpoint.exists() else {}
    judge = LettuceDetectJudge(threshold=args.threshold); started = time.perf_counter()
    pending = []
    for item in selected:
        if item["id"] in completed: continue
        source = sources[item["source_id"]]; source_info = source["source_info"]
        if source.get("task_type") == "QA" and isinstance(source_info, dict):
            contexts, question = [str(source_info.get("passages", ""))], str(source_info.get("question", ""))
        else:
            contexts = [source_info if isinstance(source_info, str) else json.dumps(source_info, ensure_ascii=False)]
            question = None
        pending.append((item, source, contexts, question))
    with checkpoint.open("a", encoding="utf-8") as handle:
        processed = 0
        for offset in range(0, len(pending), args.batch_size):
            group = pending[offset:offset + args.batch_size]
            judgments = judge.judge_many([(contexts, question, item["response"]) for item, _, contexts, question in group],
                                         batch_size=args.batch_size)
            for (item, source, _, _), judgment in zip(group, judgments):
                row = {"id": item["id"], "actual": bool(item.get("labels")), "predicted": judgment.hallucinated,
                       "score": judgment.score, "spans": judgment.spans, "task_type": source.get("task_type"),
                       "model": item.get("model")}
                handle.write(json.dumps(row, ensure_ascii=False) + "\n"); handle.flush(); completed[item["id"]] = row
                processed += 1
                if processed % 25 == 0: print(f"RAGTruth semantic benchmark: {processed}/{len(pending)} new", flush=True)
    evaluated = [completed[item["id"]] for item in selected if item["id"] in completed]
    calibration = [item for item in evaluated if int(hashlib.sha256(item["id"].encode()).hexdigest(), 16) % 5 == 0]
    holdout = [item for item in evaluated if item not in calibration]
    candidates = [value / 100 for value in range(50, 100)]
    qualified = [value for value in candidates if metrics(calibration, value)["precision"] >= .80]
    calibrated_threshold = qualified[0] if qualified else .99
    calibration_metrics = metrics(calibration, calibrated_threshold); holdout_metrics = metrics(holdout, calibrated_threshold)
    report = {"dataset": "RAGTruth", "split": "test", "quality": "good", "records": len(evaluated),
              "model": LETTUCE_MODEL, "revision": LETTUCE_REVISION, "threshold": args.threshold,
              "raw_operating_point": metrics(evaluated, args.threshold),
              "calibration_protocol": "sha256(response_id) mod 5 == 0; choose lowest 0.01 threshold with >=80% precision",
              "calibration": calibration_metrics, "held_out_evaluation": holdout_metrics,
              "task_counts": dict(Counter(item["task_type"] for item in evaluated)),
              "elapsed_seconds_this_run": round(time.perf_counter() - started, 3),
              "complete": len(evaluated) == len(selected), "target": {"recall": .70, "precision": .80,
                  "passed": holdout_metrics["recall"] >= .70 and holdout_metrics["precision"] >= .80}}
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8"); print(json.dumps(report, indent=2))
    return 0 if report["complete"] else 2


if __name__ == "__main__": raise SystemExit(main())
