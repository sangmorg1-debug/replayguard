"""Benchmark deterministic invariants standalone and stacked with ReplayGuard's baseline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from replayguard.diagnosis import diagnose, load_ground_truth, normalize_category
from replayguard.diagnostic_candidates import DiagnosticCandidate, DiagnosticEvidence, conservative_stack
from replayguard.diagnostic_corpora import load_agentrx, load_telbench, localization_metrics
from replayguard.invariants import inspect_run, inspect_semantic_spans, inspect_steps
from replayguard.otel import import_traces
from replayguard.schema import Event, EventKind, Run, utcnow


def baseline(run: Run, limit: int) -> list[DiagnosticCandidate]:
    return [DiagnosticCandidate(item.span_id, item.category, item.score, "replayguard_baseline",
            (DiagnosticEvidence("RGBASE", item.reason, item.evidence),))
            for item in diagnose(run, max_candidates=limit).suspects]


def steps_run(identifier: str, steps: list[dict]) -> Run:
    run = Run(identifier)
    for index, step in enumerate(steps):
        role = str(step.get("role", "")).lower(); location = str(step.get("index") or step.get("id") or index + 1)
        kind = EventKind.TOOL if role == "tool" else EventKind.MODEL
        run.events.append(Event(kind, str(step.get("name") or role or "step"), id=location,
            status="ok", ended_at=utcnow(), response=step.get("content")))
    return run


def aggregate_pair(rows: list[tuple[set[tuple[str, str]], set[tuple[str, str]]]]) -> dict:
    return localization_metrics([(expected, predicted) for expected, predicted in rows])


def trail(root: Path, limit: int) -> dict:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8")); baseline_rows = []; standalone = []; hybrid = []
    for record in manifest["records"]:
        run = import_traces(json.loads((root / record["trace_path"]).read_text(encoding="utf-8")))[0]
        truth = load_ground_truth(root / record["annotation_path"])
        expected = {(str(item.get("location")), normalize_category(item.get("category"))) for item in truth.get("errors", [])}
        inv = inspect_run(run, limit=limit); base = baseline(run, limit); combined = conservative_stack(base, inv, limit=limit)
        trail_category = lambda value: {"System Failure": "Service Errors", "Invalid Invocation": "Tool-related",
            "Instruction/Plan Adherence Failure": "Instruction Non-compliance"}.get(str(value), normalize_category(value))
        baseline_rows.append((expected, {(item.location, normalize_category(item.category)) for item in base}))
        standalone.append((expected, {(item.location, trail_category(item.category)) for item in inv}))
        hybrid.append((expected, {(item.location, normalize_category(item.category)) for item in combined}))
    return {"target": "joint span+TRAIL category", "baseline": aggregate_pair(baseline_rows),
            "standalone": aggregate_pair(standalone), "hybrid": aggregate_pair(hybrid)}


def telbench(path: Path, limit: int) -> dict:
    baseline_rows = []; standalone = []; hybrid = []
    for row in load_telbench(path):
        inv = inspect_semantic_spans(row["input"]["spans"], limit=limit)
        run = steps_run("telbench:" + row["id"], [{"id": span["id"], "role": "assistant", "content": span["raw"]}
                                                   for span in row["input"]["spans"]])
        base = baseline(run, limit); combined = conservative_stack(base, inv, limit=limit)
        baseline_rows.append((row["gold"], {item.location for item in base})); standalone.append((row["gold"], {item.location for item in inv})); hybrid.append((row["gold"], {item.location for item in combined}))
    return {"target": "error-span localization", "baseline": localization_metrics(baseline_rows), "standalone": localization_metrics(standalone),
            "hybrid": localization_metrics(hybrid)}


def _rx_category(value: str | None) -> str:
    compact = " ".join(str(value or "").lower().replace("/", " ").split())
    aliases = {"instruction adherence failure": "instruction plan adherence failure",
               "intent not supported": "intent not supported", "invention of new information": "invention of new information"}
    return aliases.get(compact, compact)


def agentrx(root: Path, limit: int) -> dict:
    baseline_loc = []; standalone_loc = []; hybrid_loc = []; baseline_joint = []; standalone_joint = []; hybrid_joint = []
    for row in load_agentrx(root):
        steps = row["input"]["steps"]; inv = inspect_steps(steps, limit=limit)
        base = baseline(steps_run("agentrx:" + row["id"], steps), limit); combined = conservative_stack(base, inv, limit=limit)
        expected_loc = {str(item["step"]) for item in row["gold"]}
        expected_joint = {(str(item["step"]), _rx_category(item["category"])) for item in row["gold"]}
        baseline_loc.append((expected_loc, {item.location for item in base})); standalone_loc.append((expected_loc, {item.location for item in inv})); hybrid_loc.append((expected_loc, {item.location for item in combined}))
        baseline_joint.append((expected_joint, {(item.location, _rx_category(item.category)) for item in base}))
        standalone_joint.append((expected_joint, {(item.location, _rx_category(item.category)) for item in inv}))
        hybrid_joint.append((expected_joint, {(item.location, _rx_category(item.category)) for item in combined}))
    return {"target": "step localization and AgentRx category",
            "baseline_localization": localization_metrics(baseline_loc), "standalone_localization": localization_metrics(standalone_loc), "hybrid_localization": localization_metrics(hybrid_loc),
            "baseline_joint": aggregate_pair(baseline_joint),
            "standalone_joint": aggregate_pair(standalone_joint), "hybrid_joint": aggregate_pair(hybrid_joint)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--trail", default=".verify/upstream/trail-n2")
    parser.add_argument("--external", default=".verify/upstream/diagnostic-corpora")
    parser.add_argument("--output", default=".verify/reports/stacked-invariants.json"); parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args(argv)
    if args.limit < 1: parser.error("--limit must be positive")
    external = Path(args.external); report = {"candidate_limit": args.limit,
        "trail": trail(Path(args.trail), args.limit),
        "telbench": telbench(external / "telbench/TELBench.jsonl", args.limit),
        "agentrx": agentrx(external / "agentrx", args.limit),
        "warning": "Native targets differ; scores are not directly comparable across corpora."}
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8"); print(json.dumps(report, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
