"""Audit external diagnostic corpora before using them for stacked-model claims."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from replayguard.diagnostic_corpora import load_agentrx, load_telbench


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=".verify/upstream/diagnostic-corpora")
    parser.add_argument("--output", default=".verify/reports/diagnostic-corpora.json")
    args = parser.parse_args(argv); root = Path(args.corpus)

    tel_rows = list(load_telbench(root / "telbench/TELBench.jsonl"))
    tel_dangling = 0; tel_duplicates = 0; tel_spans = 0; tel_labels = 0
    tel_benches = Counter(); tel_models = Counter()
    for row in tel_rows:
        ids = [span["id"] for span in row["input"]["spans"]]
        tel_duplicates += len(ids) - len(set(ids)); tel_spans += len(ids); tel_labels += len(row["gold"])
        tel_dangling += len(row["gold"] - set(ids)); tel_benches[str(row["meta"].get("bench", "unknown"))] += 1
        tel_models[str(row["meta"].get("model", "unknown"))] += 1

    rx_rows = list(load_agentrx(root / "agentrx")); rx_labels = 0; rx_dangling = 0
    rx_domains = Counter(); rx_categories = Counter()
    for row in rx_rows:
        available = {int(step.get("index", index + 1)) for index, step in enumerate(row["input"]["steps"])}
        for label in row["gold"]:
            rx_labels += 1; rx_categories[label["category"]] += 1
            rx_dangling += int(label["step"] not in available)
        rx_domains[row["domain"]] += 1

    report = {
        "telbench": {"cases": len(tel_rows), "spans": tel_spans, "gold_error_spans": tel_labels,
                     "duplicate_span_ids": tel_duplicates, "dangling_gold_span_ids": tel_dangling,
                     "benchmarks": dict(sorted(tel_benches.items())), "models": dict(sorted(tel_models.items()))},
        "agentrx": {"cases": len(rx_rows), "gold_failures": rx_labels,
                    "dangling_gold_steps": rx_dangling, "domains": dict(sorted(rx_domains.items())),
                    "categories": dict(rx_categories.most_common())},
        "compatibility": {"telbench_target": "span localization only",
                          "agentrx_target": "step localization plus 10-category classification",
                          "trail_joint_scores_directly_comparable": False}
    }
    if tel_dangling or tel_duplicates or rx_dangling:
        raise RuntimeError(f"corpus integrity failure: {report}")
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
