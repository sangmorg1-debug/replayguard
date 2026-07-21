"""Fetch the pinned public OpenInference span fixture used by N1 tests."""
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "5290b7b34040c140682f620772b2d6cf406f1bad"
RELATIVE = "js/packages/openinference-vercel/test/__fixtures__/v6-spans/all-spans.json"
URL = f"https://raw.githubusercontent.com/Arize-ai/openinference/{COMMIT}/{RELATIVE}"
EXPECTED = "137ddd06ad9df4be684f316d485e5c6321a71ae2049f20b293caf3838fcac252"


def main():
    target = ROOT / "tests/data/public/openinference_otel_spans.json"
    body = urllib.request.urlopen(URL, timeout=30).read()
    digest = hashlib.sha256(body).hexdigest()
    if digest != EXPECTED: raise RuntimeError(f"upstream drift: expected {EXPECTED}, got {digest}")
    # Validate before replacing the pinned local fixture.
    value = json.loads(body); assert isinstance(value, list) and value
    target.write_bytes(body)
    print(json.dumps({"file": str(target), "sha256": digest, "spans": len(value), "commit": COMMIT}, indent=2))


if __name__ == "__main__": main()
