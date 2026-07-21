"""Schema/contract files the CLI loads by default must ship inside the installed package.

`cli.py` previously resolved `--schema`/`--contract` defaults via `Path(__file__).parents[2]`,
which only works for an editable/source-tree install. A wheel install has no sibling
`schemas/` directory next to the installed package, so `verify rag aibom` and
`verify ga readiness` failed with FileNotFoundError once actually installed from a wheel.
See tools/smoke_wheel_install.py for the end-to-end reproduction against a real wheel.
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_packaged_schemas_are_loadable_via_importlib_resources():
    for name in ("aibom-v1.schema.json", "public-api-v1.contract.json"):
        packaged = resources.files("replayguard.schemas").joinpath(name)
        assert packaged.is_file(), f"{name} is not bundled inside the replayguard package"


def test_packaged_schemas_match_the_canonical_repository_copies():
    for name in ("aibom-v1.schema.json", "public-api-v1.contract.json"):
        canonical = (ROOT / "schemas" / name).read_text(encoding="utf-8")
        packaged = resources.files("replayguard.schemas").joinpath(name).read_text(encoding="utf-8")
        assert packaged == canonical, f"{name} has drifted between schemas/ and src/replayguard/schemas/"
