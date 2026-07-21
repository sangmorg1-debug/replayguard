"""Fetch the pinned public LLM-AggreFact cross-domain test parquet."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPOSITORY = "lytang/LLM-AggreFact"
REVISION = "981dfd0bd8e58e7238a9ab92b2e6ea44bce918e4"
FILES = ("README.md", "data/test-00000-of-00001.parquet")


def main() -> int:
    root = Path(".verify/upstream/llm-aggrefact"); records = []
    token = os.getenv("HF_TOKEN"); headers = {"User-Agent": "ReplayGuard-AggreFact/1.0"}
    if token: headers["Authorization"] = f"Bearer {token}"
    for name in FILES:
        url = f"https://huggingface.co/datasets/{REPOSITORY}/resolve/{REVISION}/{name}"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=120) as response: body = response.read()
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise RuntimeError("LLM-AggreFact is access-gated: accept its benchmark-only terms and set HF_TOKEN") from exc
            raise
        target = root / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(body)
        records.append({"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
    manifest = {"repository": REPOSITORY, "revision": REVISION, "files": records}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
