"""Verify ReplayGuard's ATLAS catalog against the pinned official STIX bundle."""
from __future__ import annotations

import hashlib
import json
from urllib.request import Request, urlopen

from replayguard.threat_mapping import ATLAS, ATLAS_SOURCE


def main() -> None:
    request = Request(ATLAS_SOURCE["url"], headers={"User-Agent": "ReplayGuard-ATLAS-pin/1.0"})
    with urlopen(request, timeout=60) as response:
        raw = response.read()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != ATLAS_SOURCE["sha256"]:
        raise RuntimeError(f"ATLAS STIX checksum mismatch: {digest}")
    bundle = json.loads(raw)
    upstream = {}
    for item in bundle.get("objects", []):
        if item.get("type") != "attack-pattern" or item.get("revoked") or item.get("x_mitre_deprecated"):
            continue
        reference = next((ref for ref in item.get("external_references", []) if ref.get("source_name") == "mitre-atlas"), None)
        if reference and reference.get("external_id"):
            upstream[reference["external_id"]] = item["name"]
    missing = set(ATLAS) - set(upstream)
    renamed = {key: (ATLAS[key], upstream[key]) for key in ATLAS.keys() & upstream.keys() if ATLAS[key] != upstream[key]}
    if missing or renamed:
        raise RuntimeError(f"ATLAS catalog mismatch; missing={sorted(missing)} renamed={renamed}")
    print(f"verified {len(ATLAS)} mapped/known-gap techniques against {digest}")


if __name__ == "__main__":
    main()
