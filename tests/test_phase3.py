from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

from replayguard.ci import run_ci, select_changed_cases
from replayguard.cli import main
from replayguard.schema import Event, EventKind, Run
from replayguard.suites import RegressionSuite

ROOT = Path(__file__).parents[1]


def make_suite(tmp_path):
    run = Run("authorization sk-abcdefghijklmnop", status="ok", attributes={"source_files": ["src/agent/**"]})
    run.events.append(Event(EventKind.TOOL, "read_file", status="ok", response="safe", response_hash="safe",
                            cost_usd=0.01, latency_ms=10))
    suite = RegressionSuite("ci", baseline={"max_cost_usd": 0.05, "max_latency_ms": 100, "prohibited_tools": ["send_secrets"]})
    case = suite.add_run(run)
    case.evaluations = [{"method": "exact", "expected": "safe"}]
    path = tmp_path / "suite.json"
    suite.save(path)
    return suite, case, path


def test_ci_pass_emits_hash_addressed_private_evidence(tmp_path):
    suite, case, path = make_suite(tmp_path)
    result = run_ci(path, output_dir=tmp_path / "report", commit_sha="abc123")
    assert result.passed and result.selected_cases == 1
    assert result.bundle_sha256 in result.bundle_path.name
    evidence = json.loads(result.bundle_path.read_text())
    assert evidence["commit_sha"] == "abc123"
    assert evidence["results_sha256"] == hashlib.sha256(result.results_path.read_bytes()).hexdigest()
    assert "abcdefghijklmnop" not in result.report_path.read_text()
    assert "SAFE TO MERGE" in result.report_path.read_text()


def test_ci_blocks_tool_cost_and_answer_regression(tmp_path):
    suite, case, path = make_suite(tmp_path)
    candidate = Run.from_dict(deepcopy(case.source_run))
    candidate.events[0].response = "changed"
    candidate.events[0].response_hash = "changed"
    candidate.events[0].cost_usd = 0.20
    candidate.events.append(Event(EventKind.TOOL, "send_secrets", status="ok"))
    candidates = tmp_path / "candidates.json"
    candidates.write_text(json.dumps({case.id: candidate.to_dict()}))
    result = run_ci(path, candidate_map=candidates, output_dir=tmp_path / "blocked")
    report = result.report_path.read_text()
    assert not result.passed
    assert "BLOCKED" in report and "send_secrets" in report
    assert "exact" in report and "security_invariant" in report


def test_changed_case_selection_matches_paths_and_keeps_unscoped_cases(tmp_path):
    suite, case, path = make_suite(tmp_path)
    other = suite.add_run(Run("global", status="ok"))
    selected = select_changed_cases(suite, ["docs/readme.md"])
    assert [item.id for item in selected.cases] == [other.id]
    selected = select_changed_cases(suite, ["src/agent/main.py"])
    assert {item.id for item in selected.cases} == {case.id, other.id}


def test_ci_cli_exit_codes(tmp_path, capsys):
    _, _, path = make_suite(tmp_path)
    assert main(["ci", "--suite", str(path), "--output", str(tmp_path / "out")]) == 0
    assert '"passed": true' in capsys.readouterr().out.lower()


def test_workflow_is_fork_safe_and_locally_runnable():
    workflow = (ROOT / ".github/workflows/replayguard.yml").read_text()
    action = (ROOT / "action.yml").read_text()
    assert "pull_request_target" not in workflow
    assert "pull_request:" in workflow
    assert "contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "secrets." not in workflow and "secrets." not in action
    assert "uses: ./" in workflow and "using: composite" in action

