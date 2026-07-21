"""Run the checksum-pinned upstream TRAIL scorer unchanged on experiment predictions."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

REVISION = "0ffbed9db859b4a66250dc783fa4dccf86869595"
URL = f"https://raw.githubusercontent.com/patronus-ai/trail-benchmark/{REVISION}/benchmarking/calculate_scores.py"
EXPECTED_SHA256 = "ed81ebd529da189425efb9c58183e7c1dcd55a234264ea039e03428bcc5f24d2"


def digest(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_scorer(path: Path) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(urlopen(URL, timeout=60).read())
    if digest(path) != EXPECTED_SHA256: raise ValueError(f"official scorer checksum mismatch: {digest(path)}")


def run(corpus: Path, predictions: Path, scorer_path: Path) -> dict:
    spec = importlib.util.spec_from_file_location("official_trail_scores", scorer_path)
    scorer = importlib.util.module_from_spec(spec); spec.loader.exec_module(scorer)
    result = {"scorer_revision": REVISION, "scorer_sha256": EXPECTED_SHA256, "methods": {},
              "known_upstream_parse_failures": []}
    for annotation in corpus.glob("processed_annotations_*/*.json"):
        try: json.loads(annotation.read_text(encoding="utf-8"))
        except json.JSONDecodeError: result["known_upstream_parse_failures"].append(annotation.relative_to(corpus).as_posix())
    for method_dir in sorted(path for path in predictions.iterdir() if path.is_dir()):
        result["methods"][method_dir.name] = {}
        for label, annotation_dir, prediction_dir in (
            ("GAIA", corpus / "processed_annotations_gaia", method_dir / "GAIA"),
            ("SWE Bench", corpus / "processed_annotations_swe_bench", method_dir / "SWE_Bench")):
            scores = scorer.main(str(annotation_dir), str(prediction_dir))
            result["methods"][method_dir.name][label] = {key: scores[key] for key in
                ("weighted_f1", "location_accuracy", "joint_accuracy")}
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--corpus", type=Path, default=Path(".verify/upstream/trail-hf"))
    parser.add_argument("--predictions", type=Path, default=Path(".verify/trail-tiny-experiment/official_predictions"))
    parser.add_argument("--scorer", type=Path, default=Path(".verify/upstream/trail-official/calculate_scores.py"))
    parser.add_argument("--output", type=Path, default=Path(".verify/trail-tiny-experiment/official-scorer-results.json"))
    args = parser.parse_args(argv); ensure_scorer(args.scorer)
    if not sys.flags.utf8_mode:
        command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), *sys.argv[1:]]
        return subprocess.run(command, env={**os.environ, "PYTHONUTF8": "1"}).returncode
    report = run(args.corpus, args.predictions, args.scorer); args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8"); print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
