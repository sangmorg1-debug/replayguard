from __future__ import annotations

import hashlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from jsonschema import validate


def generate_aibom(manifest: dict[str, Any]) -> dict[str, Any]:
    components = []
    mapping = {"models": "machine-learning-model", "prompts": "prompt", "agents": "agent", "tools": "tool",
               "evaluation_suites": "evaluation-suite", "retrieval_collections": "data", "embedding_models": "machine-learning-model",
               "data_sources": "dataset"}
    for group, kind in mapping.items():
        for raw in manifest.get(group, []):
            item = {"type": kind, **raw} if isinstance(raw, dict) else {"type": kind, "name": str(raw)}
            if "sha256" not in item: item["sha256"] = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
            components.append(item)
    packages = manifest.get("packages")
    if packages == "environment":
        packages = [{"name": item.metadata["Name"], "version": item.version} for item in importlib.metadata.distributions() if item.metadata.get("Name")]
    for package in packages or []: components.append({"type": "library", **package})
    bom = {"bomFormat": "ReplayGuard-AIBOM", "specVersion": "1.0", "serialNumber": f"urn:uuid:{uuid4()}",
           "metadata": {"timestamp": datetime.now(timezone.utc).isoformat(), "application": manifest["application"],
                        "generation_context": manifest.get("generation_context", {}), "tool": {"name": "replayguard", "version": "1.0.0"}},
           "components": components, "dependencies": manifest.get("dependencies", [])}
    bom["digest"] = hashlib.sha256(json.dumps(bom, sort_keys=True).encode()).hexdigest()
    return bom


def validate_aibom(bom: dict[str, Any], schema_path: str | Path) -> None:
    validate(bom, json.loads(Path(schema_path).read_text(encoding="utf-8")))
