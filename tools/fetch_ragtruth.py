"""Fetch a pinned, manually annotated RAGTruth evaluation slice.

The complete upstream files remain in .verify/upstream; only a compact benchmark
with provenance and labels is written to tests/data.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

COMMIT = "c103204b9ce28d6bbad859304bf30de72b8ed8fe"
BASE = f"https://raw.githubusercontent.com/ParticleMedia/RAGTruth/{COMMIT}/dataset"
ROOT = Path(__file__).resolve().parents[1]


def download(name: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists(): urllib.request.urlretrieve(f"{BASE}/{name}", target)


def main() -> None:
    upstream = ROOT / ".verify/upstream/ragtruth"
    response_path, source_path = upstream / "response.jsonl", upstream / "source_info.jsonl"
    download("response.jsonl", response_path); download("source_info.jsonl", source_path)
    sources = {item["source_id"]: item for item in map(json.loads, source_path.open(encoding="utf-8"))}
    positive, negative = [], []
    for item in map(json.loads, response_path.open(encoding="utf-8")):
        if item["split"] != "test" or item["quality"] != "good": continue
        target = positive if item["labels"] else negative
        if len(target) < 50: target.append(item)
        if len(positive) == len(negative) == 50: break
    records = []
    for item in positive + negative:
        source = sources[item["source_id"]]
        records.append({"id": item["id"], "source_id": item["source_id"], "task_type": source["task_type"],
                        "query": source["prompt"], "source": source["source_info"], "response": item["response"],
                        "model": item["model"], "labels": item["labels"], "has_hallucination": bool(item["labels"])})
    output = {"dataset": "RAGTruth", "license": "MIT", "upstream": "https://github.com/ParticleMedia/RAGTruth",
              "commit": COMMIT, "sampling": "first 50 labeled and 50 unlabeled good-quality test responses", "records": records}
    target = ROOT / "tests/data/ragtruth-sample.json"
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(target), "records": len(records), "labeled": len(positive), "unlabeled": len(negative)}, indent=2))


if __name__ == "__main__": main()
