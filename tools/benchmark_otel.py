"""Reproduce N1 semantic round-trip results on pinned real traces."""
import argparse
import hashlib
import json
from pathlib import Path

from replayguard.otel import coverage, export_otlp, import_traces, normalized

ROOT = Path(__file__).resolve().parents[1]


def measure(path: Path):
    document = json.loads(path.read_text(encoding="utf-8")); runs = import_traces(document); exported = export_otlp(runs)
    return {"file": str(path), "runs": len(runs), "spans": sum(len(item.events) for item in runs),
            "semantic_roundtrip": normalized(document) == normalized(exported), "coverage": coverage(runs)}


def measure_trail_corpus(root: Path) -> dict:
    """Verify and round-trip every trace in a fetch_trail_n2.py public corpus."""
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = []
    aggregate = {"runs": 0, "spans": 0, "attribute_occurrences": {}, "recognized_occurrences": {}}
    for record in manifest["records"]:
        path = root / record["trace_path"]
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        if digest != record["trace_sha256"]:
            raise ValueError(f"TRAIL checksum mismatch for {record['trace_path']}: {digest}")
        result = measure(path)
        if not result["semantic_roundtrip"]:
            raise ValueError(f"TRAIL semantic round-trip failed for {record['trace_path']}")
        item_coverage = result.pop("coverage")
        result.update({"trace_id": record["trace_id"], "split": record["split"], "sha256": digest})
        results.append(result)
        aggregate["runs"] += item_coverage["runs"]
        aggregate["spans"] += item_coverage["spans"]
        for group in ("attribute_occurrences", "recognized_occurrences"):
            for key, value in item_coverage[group].items():
                aggregate[group][key] = aggregate[group].get(key, 0) + value
    splits = {name: sum(item["split"] == name for item in results) for name in sorted({item["split"] for item in results})}
    return {
        "repository": manifest["repository"], "revision": manifest["revision"],
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "trace_files": len(results), "splits": splits, "semantic_roundtrip_failures": 0,
        "coverage": aggregate, "results": results,
    }


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--trail", action="store_true")
    parser.add_argument("--trail-corpus", type=Path,
                        help="directory produced by fetch_trail_n2.py; verifies every pinned trace")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(); paths = [ROOT / "tests/data/public/openinference_otel_spans.json"]
    if args.trail:
        paths.append(ROOT / ".verify/upstream/trail/0035f455b3ff2295167a844f04d85d34.json")
    report = {"results": [measure(path) for path in paths]}
    if args.trail_corpus:
        report["trail_corpus"] = measure_trail_corpus(args.trail_corpus)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__": main()
