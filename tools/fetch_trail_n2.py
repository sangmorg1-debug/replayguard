"""Fetch a deterministic, non-redistributed TRAIL benchmark slice from public GitHub."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

REVISION = "0ffbed9db859b4a66250dc783fa4dccf86869595"
REPOSITORY = "patronus-ai/trail-benchmark"
API = f"https://api.github.com/repos/{REPOSITORY}/git/trees/{REVISION}?recursive=1"
RAW = f"https://raw.githubusercontent.com/{REPOSITORY}/{REVISION}/"


def download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "ReplayGuard-TRAIL-benchmark/1.0"})
    with urlopen(request, timeout=90) as response:
        return response.read()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=".verify/upstream/trail-n2")
    parser.add_argument("--per-split", type=int, default=999, help="maximum traces per split (default: all)")
    args = parser.parse_args(argv)
    if args.per_split < 1:
        parser.error("--per-split must be positive")

    tree = json.loads(download(API))["tree"]
    paths = {item["path"] for item in tree if item.get("type") == "blob"}
    selected: list[tuple[str, str, str]] = []
    for split, annotation_dir in (("GAIA", "processed_annotations_gaia"),
                                  ("SWE Bench", "processed_annotations_swe_bench")):
        traces = sorted(path for path in paths if path.startswith(f"benchmarking/data/{split}/") and path.endswith(".json"))
        for trace_path in traces[:args.per_split]:
            filename = Path(trace_path).name
            annotation_path = f"benchmarking/{annotation_dir}/{filename}"
            if annotation_path not in paths:
                raise RuntimeError(f"annotation missing for {trace_path}")
            selected.append((split, trace_path, annotation_path))

    root = Path(args.output); records = []
    for split, trace_path, annotation_path in selected:
        record = {"split": split, "trace_id": Path(trace_path).stem}
        for kind, source in (("trace", trace_path), ("annotation", annotation_path)):
            body = download(RAW + quote(source, safe="/"))
            target = root / ("traces" if kind == "trace" else "annotations") / split.replace(" ", "_") / Path(source).name
            target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(body)
            record[f"{kind}_path"] = target.relative_to(root).as_posix()
            record[f"{kind}_sha256"] = hashlib.sha256(body).hexdigest()
        records.append(record)
    counts = {split: sum(record["split"] == split for record in records) for split in ("GAIA", "SWE Bench")}
    manifest = {"repository": REPOSITORY, "revision": REVISION,
                "selection": f"all public traces at the revision ({counts['GAIA']} GAIA, {counts['SWE Bench']} SWE Bench)" if len(records) == 148
                             else f"first {args.per_split} trace IDs lexicographically per split",
                "records": records}
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(root.resolve()), "traces": len(records), "revision": REVISION}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
