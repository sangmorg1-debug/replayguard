"""Download and verify the full official SWE-bench Verified snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

from replayguard.scale import SWE_BENCH_VERIFIED


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--output", default=".verify/upstream/swe-bench-verified.parquet")
    args = parser.parse_args(); target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    request = Request(SWE_BENCH_VERIFIED["url"], headers={"User-Agent": "ReplayGuard-SWE-bench-ingest/1.0"})
    with urlopen(request, timeout=120) as response: raw = response.read()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != SWE_BENCH_VERIFIED["sha256"]: raise RuntimeError(f"checksum mismatch: {digest}")
    target.write_bytes(raw)
    metadata = {**SWE_BENCH_VERIFIED, "downloaded_file": target.name, "bytes": len(raw)}
    target.with_suffix(".source.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"verified {digest}; wrote {target}")


if __name__ == "__main__": main()
