from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redaction import Redactor
from .schema import Run, SCHEMA_VERSION
from .suites import RegressionCase, RegressionSuite, SuiteResult, SuiteRunner


@dataclass
class CIResult:
    passed: bool
    report_path: Path
    results_path: Path
    bundle_path: Path
    bundle_sha256: str
    selected_cases: int


def select_changed_cases(suite: RegressionSuite, changed_files: list[str]) -> RegressionSuite:
    if not changed_files:
        return suite
    selected: list[RegressionCase] = []
    for case in suite.cases:
        patterns = [tag[5:] for tag in case.tags if tag.startswith("path:")]
        source_patterns = case.source_run.get("attributes", {}).get("source_files", [])
        patterns.extend(source_patterns if isinstance(source_patterns, list) else [])
        if not patterns or any(fnmatch.fnmatch(path, pattern) for path in changed_files for pattern in patterns):
            selected.append(case)
    return RegressionSuite(suite.name, suite.version, selected, suite.baseline)


def load_candidate_map(path: str | Path | None) -> dict[str, Run]:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {case_id: Run.from_dict(run) for case_id, run in data.items()}


def run_ci(suite_path: str | Path, *, candidate_map: str | Path | None = None,
           changed_files: list[str] | None = None, output_dir: str | Path = ".verify/report",
           commit_sha: str | None = None) -> CIResult:
    source_suite = RegressionSuite.load(suite_path)
    suite = select_changed_cases(source_suite, changed_files or [])
    candidates = load_candidate_map(candidate_map)
    result = SuiteRunner().run(suite, candidates)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    safe = Redactor().redact(result.to_dict())
    results_path = out / "results.json"
    results_path.write_text(json.dumps(safe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_path = out / "report.md"
    report_path.write_text(Redactor().redact(render_markdown(result, suite_path, changed_files or [])), encoding="utf-8")
    evidence = {
        "format": "replayguard-evidence-v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "commit_sha": commit_sha or os.getenv("GITHUB_SHA") or "local",
        "trace_schema_version": SCHEMA_VERSION, "suite_version": suite.version,
        "suite_sha256": _file_hash(Path(suite_path)), "candidate_map_sha256": _optional_hash(candidate_map),
        "evaluator_versions": sorted({evaluation.evaluator_version for item in result.results for evaluation in item.evaluations}),
        "model_identifiers": _identifiers(suite, ("model", "model_id", "model_version")),
        "prompt_identifiers": _identifiers(suite, ("prompt_id", "prompt_version")),
        "tool_fixture_hashes": sorted({
            value for case in suite.cases for event in case.source_run.get("events", [])
            if event.get("kind") == "tool" for value in (event.get("request_hash"), event.get("response_hash")) if value
        }),
        "environment": {"python": platform.python_version(), "platform": platform.system(),
                        "github_run_id": os.getenv("GITHUB_RUN_ID")},
        "summary": {"total": result.total, "passed": result.passed,
                    "deterministic_failures": result.deterministic_failures},
        "results_sha256": _file_hash(results_path), "report_sha256": _file_hash(report_path),
    }
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    bundle_path = out / f"evidence-{digest}.json"
    bundle_path.write_bytes(json.dumps(evidence, indent=2, ensure_ascii=False).encode() + b"\n")
    return CIResult(result.total == result.passed, report_path, results_path, bundle_path, digest, result.total)


def render_markdown(result: SuiteResult, suite_path: str | Path, changed_files: list[str]) -> str:
    failed = [item for item in result.results if not item.passed]
    deterministic = sum(not item.deterministic_passed for item in result.results)
    probabilistic = sum(any(not e.deterministic for e in item.evaluations) for item in result.results)
    categories = sorted({change["category"] for item in result.results for change in item.comparison["changes"]})
    new_tools = []
    for item in result.results:
        for change in item.comparison["changes"]:
            if change["category"] == "tool_behavior":
                before = {row[0] for row in change["before"]}
                new_tools.extend(sorted({row[0] for row in change["after"]} - before))
    verdict = "SAFE TO MERGE" if not failed else "BLOCKED"
    lines = [
        "# ReplayGuard PR evidence", "", f"## {verdict}", "",
        f"- Cases: **{result.passed}/{result.total} passed**",
        f"- Deterministic failures: **{deterministic}**",
        f"- Cases with probabilistic judgments: **{probabilistic}**",
        f"- Changed behavior categories: {', '.join(categories) if categories else 'none'}",
        f"- New tools or permissions: {', '.join(sorted(set(new_tools))) if new_tools else 'none'}",
        f"- Changed files considered: {len(changed_files) if changed_files else 'all cases'}", "",
    ]
    if failed:
        lines.extend(["## Failures", "", "| Case | Deterministic | Failed checks |", "|---|---:|---|"])
        for item in failed[:50]:
            checks = [e.method for e in item.evaluations if e.passed is False]
            lines.append(f"| `{_md(item.name)}` | {'yes' if not item.deterministic_passed else 'no'} | {_md(', '.join(checks) or 'behavior changed')} |")
        lines.append("")
    lines.extend(["## Reproduce locally", "", "```text", f"verify ci --suite {suite_path}", "```", "",
                  "Deterministic failures are merge-blocking. Probabilistic judgments are labeled and cannot override them.", ""])
    return "\n".join(lines)


def _md(value: str) -> str:
    return str(value).replace("|", "\\|").replace("`", "'").replace("\n", " ")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _optional_hash(path: str | Path | None) -> str | None:
    return _file_hash(Path(path)) if path else None


def _identifiers(suite: RegressionSuite, keys: tuple[str, ...]) -> list[str]:
    values = set()
    for case in suite.cases:
        attributes = case.source_run.get("attributes", {})
        for key in keys:
            if attributes.get(key) is not None:
                values.add(str(attributes[key]))
        for event in case.source_run.get("events", []):
            for key in keys:
                if event.get("attributes", {}).get(key) is not None:
                    values.add(str(event["attributes"][key]))
    return sorted(values)
