"""Fetch one pinned TRAIL trace from the authors' public MIT GitHub repository.

The file is stored under ignored .verify/upstream and is never copied into the
redistributable test corpus. This does not access or bypass the gated HF files.
"""
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "0ffbed9db859b4a66250dc783fa4dccf86869595"
TRACE = "0035f455b3ff2295167a844f04d85d34"
URL = f"https://raw.githubusercontent.com/patronus-ai/trail-benchmark/{COMMIT}/benchmarking/data/GAIA/{TRACE}.json"
EXPECTED = "a8b31d38493a22091788f99e32beb79b801e35269f626b6a0de0446f435df38e"


def main():
    target = ROOT / f".verify/upstream/trail/{TRACE}.json"; target.parent.mkdir(parents=True, exist_ok=True)
    body = urllib.request.urlopen(URL, timeout=30).read(); digest = hashlib.sha256(body).hexdigest()
    if digest != EXPECTED: raise RuntimeError(f"upstream drift: expected {EXPECTED}, got {digest}")
    data = json.loads(body)
    if data.get("trace_id") != TRACE or not data.get("spans"): raise RuntimeError("unexpected TRAIL shape")
    target.write_bytes(body)
    print(json.dumps({"file": str(target), "trace_id": TRACE, "sha256": digest, "commit": COMMIT}, indent=2))


if __name__ == "__main__": main()
