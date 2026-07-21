"""Fetch the access-gated TRAIL dataset into a private ignored cache and pin every file."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REPOSITORY = "PatronusAI/TRAIL"
REVISION = "b424ce63d5973d5dcd7169b1bc3c07ccdee276d1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(root: Path) -> dict:
    records = []
    for split, annotation_dir in (("GAIA", "processed_annotations_gaia"),
                                  ("SWE Bench", "processed_annotations_swe_bench")):
        for trace in sorted((root / split).glob("*.json")):
            annotation = root / annotation_dir / trace.name
            if not annotation.is_file():
                raise ValueError(f"missing TRAIL annotation for {split}/{trace.name}")
            records.append({
                "split": split, "trace_id": trace.stem,
                "trace_path": trace.relative_to(root).as_posix(), "trace_sha256": sha256(trace),
                "annotation_path": annotation.relative_to(root).as_posix(),
                "annotation_sha256": sha256(annotation),
            })
    if len(records) != 148:
        raise ValueError(f"expected 148 TRAIL traces at pinned revision, found {len(records)}")
    return {
        "repository": REPOSITORY, "repository_type": "dataset", "revision": REVISION,
        "access": "gated; authorized account required; files must not be redistributed",
        "records": records,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(".verify/upstream/trail-hf"))
    parser.add_argument("--offline", action="store_true", help="verify an existing authorized snapshot")
    args = parser.parse_args(argv)
    if not args.offline:
        from huggingface_hub import snapshot_download
        snapshot_download(REPOSITORY, repo_type="dataset", revision=REVISION,
                          local_dir=args.output, allow_patterns=["*.json", "README.md"], max_workers=8)
    manifest = build_manifest(args.output)
    target = args.output / "manifest.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "revision": REVISION,
                      "traces": len(manifest["records"]), "manifest_sha256": sha256(target)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
