"""Build the real Phase-3 ship-demo artifacts: one passing CI run, one deliberately blocked run.

Reproduce:
    python tools/build_ship_demo.py
    verify ci --suite examples/public-regression-suite.json --output .verify/ship-demo/ci-passing
    verify ci --suite examples/public-regression-suite.json \
        --candidate-map .verify/ship-demo/regressed-candidate-map.json \
        --output .verify/ship-demo/ci-blocked
"""
from __future__ import annotations

import json
from pathlib import Path

from replayguard.schema import Event, EventKind, Run

ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "examples/public-regression-suite.json"
OUTPUT_DIR = ROOT / ".verify/ship-demo"


def build_regressed_candidate_map() -> Path:
    suite = json.loads(SUITE_PATH.read_text(encoding="utf-8"))
    case = suite["cases"][0]
    candidate = Run.from_dict(case["source_run"])

    # Changed answer: the fixture placeholder response no longer matches the "exact" evaluation.
    tool_event = next(event for event in candidate.events if event.kind == EventKind.TOOL)
    tool_event.response = "unexpected changed answer"
    tool_event.response_hash = "changed"

    # Increased cost: baseline's max_cost_usd is 0, so any positive cost now fails the budget gate.
    tool_event.cost_usd = 0.50

    # Unexpected tool call: "send_secrets" is in the suite's prohibited_tools list.
    candidate.events.append(Event(EventKind.TOOL, "send_secrets", status="ok"))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / "regressed-candidate-map.json"
    path.write_text(json.dumps({case["id"]: candidate.to_dict()}, indent=2), encoding="utf-8")
    print(f"wrote {path} for case {case['id']} ({case['name']})")
    return path


if __name__ == "__main__":
    build_regressed_candidate_map()
