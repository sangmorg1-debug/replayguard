"""Benchmark the local claim/evidence graph alone and in the diagnostic stack."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from replayguard.claim_graph import diagnose_claim_graph
from replayguard.diagnosis import diagnose, load_ground_truth
from replayguard.diagnostic_candidates import conservative_stack, merge_candidates
from replayguard.diagnostic_corpora import load_agentrx, load_telbench, localization_metrics
from replayguard.invariants import inspect_run, inspect_semantic_spans, inspect_steps
from replayguard.otel import import_traces
from replayguard.schema import Event, EventKind, Run, utcnow


def text(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def event_steps(run: Run) -> list[tuple[str, str]]:
    return [(event.id, " ".join((f"kind={event.kind.value} name={event.name} status={event.status}",
             "request=" + text(event.request), "response=" + text(event.response), "error=" + text(event.error))))
            for event in sorted(run.events, key=lambda item: (item.started_at, item.id))]


def baseline(run: Run, limit: int):
    from replayguard.diagnostic_candidates import DiagnosticCandidate, DiagnosticEvidence
    return [DiagnosticCandidate(item.span_id, item.category, item.score, "replayguard_baseline",
            (DiagnosticEvidence("RGBASE", item.reason, item.evidence),)) for item in diagnose(run, max_candidates=limit).suspects]


def step_run(identifier: str, rows: list[dict]) -> Run:
    run = Run(identifier)
    for index, row in enumerate(rows):
        location = str(row.get("index") or row.get("id") or index + 1)
        run.events.append(Event(EventKind.TOOL if str(row.get("role", "")).lower() == "tool" else EventKind.MODEL,
            str(row.get("role") or "step"), id=location, status="ok", ended_at=utcnow(), response=row.get("content")))
    return run


def locations(items) -> set[str]: return {item.location for item in items}


def score(rows, field): return localization_metrics([(row["expected"], row[field]) for row in rows])


def evaluate_case(expected, base, invariant, claim, limit):
    secondary = merge_candidates(invariant, claim, limit=limit)
    hybrid = conservative_stack(base, secondary, limit=limit)
    return {"expected": set(expected), "baseline": locations(base), "invariants": locations(invariant),
            "claim_graph": locations(claim), "hybrid": locations(hybrid)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--trail", default=".verify/upstream/trail-n2")
    parser.add_argument("--external", default=".verify/upstream/diagnostic-corpora")
    parser.add_argument("--output", default=".verify/reports/claim-graph.json"); parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args(argv); limit = args.limit; reports = {}
    trail_root = Path(args.trail); manifest = json.loads((trail_root / "manifest.json").read_text(encoding="utf-8")); rows = []
    for record in manifest["records"]:
        run = import_traces(json.loads((trail_root / record["trace_path"]).read_text(encoding="utf-8")))[0]
        truth = load_ground_truth(trail_root / record["annotation_path"]); expected = {str(item.get("location")) for item in truth.get("errors", [])}
        claim, _ = diagnose_claim_graph(event_steps(run), max_candidates=limit)
        rows.append(evaluate_case(expected, baseline(run, limit), inspect_run(run, limit=limit), claim, limit))
    reports["trail_location"] = {field: score(rows, field) for field in ("baseline", "invariants", "claim_graph", "hybrid")}

    external = Path(args.external); rows = []
    for row in load_telbench(external / "telbench/TELBench.jsonl"):
        steps = [(span["id"], span["raw"]) for span in row["input"]["spans"]]
        raw = [{"id": a, "role": "assistant", "content": b} for a, b in steps]; run = step_run("tel:" + row["id"], raw)
        claim, _ = diagnose_claim_graph(steps, max_candidates=limit)
        rows.append(evaluate_case(row["gold"], baseline(run, limit), inspect_semantic_spans(row["input"]["spans"], limit=limit), claim, limit))
    reports["telbench_location"] = {field: score(rows, field) for field in ("baseline", "invariants", "claim_graph", "hybrid")}

    rows = []
    for row in load_agentrx(external / "agentrx"):
        raw = row["input"]["steps"]; steps = [(str(item.get("index") or index + 1), text(item.get("content"))) for index, item in enumerate(raw)]
        claim, _ = diagnose_claim_graph(steps, max_candidates=limit); expected = {str(item["step"]) for item in row["gold"]}
        rows.append(evaluate_case(expected, baseline(step_run("rx:" + row["id"], raw), limit), inspect_steps(raw, limit=limit), claim, limit))
    reports["agentrx_location"] = {field: score(rows, field) for field in ("baseline", "invariants", "claim_graph", "hybrid")}

    report = {"candidate_limit": limit, "method": "training-free local claim/evidence graph", "corpora": reports,
              "warning": "Location metrics only; not TRAIL joint span+category accuracy."}
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
