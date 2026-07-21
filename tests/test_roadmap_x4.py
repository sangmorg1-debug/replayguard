import json
import shutil
import subprocess
from pathlib import Path

import pytest
from jsonschema import validate

from replayguard.datasets import load_bfcl, load_tau_voice_trace
from replayguard.replay import ReplayMode, Replayer
from replayguard.schema import Run

ROOT = Path(__file__).parents[1]
SDK = ROOT / "sdk/typescript"
PUBLIC = ROOT / "tests/data/public"
SCHEMA = json.loads((ROOT / "schemas/trace-v1.schema.json").read_text(encoding="utf-8"))
NPM = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
NODE = shutil.which("node") or "node"


@pytest.fixture(scope="module", autouse=True)
def build_typescript_sdk():
    subprocess.run([NPM, "run", "build"], cwd=SDK, check=True, shell=False)


def stable_events(run):
    return [(item.kind.value if hasattr(item.kind, "value") else item.kind, item.name, item.request, item.response,
             item.attributes, item.usage, item.status) for item in run.events]


def test_typescript_records_real_bfcl_and_python_replays_exactly(tmp_path):
    output = tmp_path / "typescript-bfcl.json"
    subprocess.run([NODE, "dist/tools/conformance.js", "bfcl",
                    str(PUBLIC / "bfcl_cases.jsonl"), str(PUBLIC / "bfcl_answers.jsonl"), str(output), "25"],
                   cwd=SDK, check=True)
    values = json.loads(output.read_text(encoding="utf-8"))
    assert len(values) == 25 and {item["attributes"]["dataset"] for item in values} == {"BFCL-v4"}
    for value in values:
        validate(value, SCHEMA)
        source = Run.from_dict(value)
        result = Replayer().replay(source, mode=ReplayMode.EXACT)
        assert result.live_calls == 0 and result.fixture_hits == len(source.events)
        assert stable_events(result.run) == stable_events(source)


def test_python_real_bfcl_and_tau2_traces_validate_and_replay_in_typescript(tmp_path):
    bfcl = next(load_bfcl(PUBLIC / "bfcl_cases.jsonl", PUBLIC / "bfcl_answers.jsonl"))
    tau = load_tau_voice_trace(PUBLIC / "tau_voice_trace_1.json")
    source_path, output_path = tmp_path / "python-traces.json", tmp_path / "ts-replays.json"
    source_path.write_text(json.dumps([bfcl.to_dict(), tau.to_dict()]), encoding="utf-8")
    subprocess.run([NODE, "dist/tools/conformance.js", "validate-replay", str(source_path), str(output_path)],
                   cwd=SDK, check=True)
    results = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(results) == 2
    for original, result in zip((bfcl, tau), results):
        assert result["live_calls"] == 0 and result["fixture_hits"] == len(original.events)
        validate(result["run"], SCHEMA)
        assert stable_events(Run.from_dict(result["run"])) == stable_events(original)


def test_typescript_package_has_no_runtime_dependencies_and_pins_toolchain():
    package = json.loads((SDK / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((SDK / "package-lock.json").read_text(encoding="utf-8"))
    assert "dependencies" not in package
    assert package["devDependencies"] == {"@types/node": "22.15.30", "typescript": "5.9.3"}
    assert lock["lockfileVersion"] == 3
