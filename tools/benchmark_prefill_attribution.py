"""Resume-safe real-data benchmark for paper-spec prefill attribution."""
from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

from replayguard.diagnosis import diagnose, load_ground_truth
from replayguard.diagnostic_corpora import load_agentrx, load_telbench, localization_metrics
from replayguard.otel import import_traces
from replayguard.prefill_attribution import QwenPrefillBackend, attribute
from replayguard.schema import Event, EventKind, Run, utcnow


def text(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def run_steps(run: Run) -> list[tuple[str, str]]:
    return [(event.id, " ".join((f"kind={event.kind.value} name={event.name} status={event.status}",
             "request=" + text(event.request), "response=" + text(event.response), "error=" + text(event.error))))
            for event in sorted(run.events, key=lambda item: (item.started_at, item.id))]


def baseline_locations(run: Run, limit: int) -> list[str]:
    return list(dict.fromkeys(item.span_id for item in diagnose(run, max_candidates=limit).suspects))[:limit]


def sequence_run(identifier: str, steps: list[dict]) -> Run:
    run = Run(identifier)
    for index, step in enumerate(steps):
        location = str(step.get("index") or step.get("id") or index + 1)
        run.events.append(Event(EventKind.TOOL if str(step.get("role", "")).lower() == "tool" else EventKind.MODEL,
            str(step.get("role") or "step"), id=location, status="ok", ended_at=utcnow(), response=step.get("content")))
    return run


def safe_hybrid(primary: list[str], secondary: list[str], limit: int) -> list[str]:
    return list(dict.fromkeys((*primary, *secondary)))[:limit]


def load_completed(path: Path) -> dict[str, dict]:
    if not path.exists(): return {}
    return {row["key"]: row for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
            for row in [json.loads(line)]}


def append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as target: target.write(json.dumps(row, ensure_ascii=False) + "\n")


def cases(args):
    if "trail" in args.corpora:
        root = Path(args.trail); manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        for record in manifest["records"]:
            run = import_traces(json.loads((root / record["trace_path"]).read_text(encoding="utf-8")))[0]
            truth = load_ground_truth(root / record["annotation_path"])
            expected = {str(item.get("location")) for item in truth.get("errors", [])}
            yield "trail", record["trace_id"], run_steps(run), expected, baseline_locations(run, 10), .5, 10
    if "telbench" in args.corpora:
        for row in load_telbench(Path(args.external) / "telbench/TELBench.jsonl"):
            steps = [(span["id"], span["raw"]) for span in row["input"]["spans"]]
            run = sequence_run("telbench:" + row["id"], [{"id": a, "role": "assistant", "content": b} for a, b in steps])
            yield "telbench", row["id"], steps, row["gold"], baseline_locations(run, 3), .5, 3
    if "agentrx" in args.corpora:
        for row in load_agentrx(Path(args.external) / "agentrx"):
            raw = row["input"]["steps"]; steps = [(str(step.get("index") or i + 1), text(step.get("content"))) for i, step in enumerate(raw)]
            expected = {str(item["step"]) for item in row["gold"]}
            yield ("agentrx", row["domain"] + ":" + row["id"], steps, expected,
                   baseline_locations(sequence_run("agentrx:" + row["id"], raw), 3), .2, 3)


def summarize(rows: list[dict], corpus: str) -> dict:
    selected = [row for row in rows if row["corpus"] == corpus and not row.get("error")]
    def score(field): return localization_metrics([(set(row["expected"]), set(row[field])) for row in selected])
    return {"processed": len(selected), "failed": sum(row["corpus"] == corpus and bool(row.get("error")) for row in rows),
            "baseline": score("baseline"), "prefill": score("prefill"), "hybrid": score("hybrid"),
            "mean_seconds": sum(row["seconds"] for row in selected) / len(selected) if selected else 0,
            "input_tokens": sum(row["input_tokens"] for row in selected), "decoded_tokens": 0}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--trail", default=".verify/upstream/trail-n2")
    parser.add_argument("--external", default=".verify/upstream/diagnostic-corpora")
    parser.add_argument("--work", default=".verify/prefill-attribution/predictions.jsonl")
    parser.add_argument("--output", default=".verify/reports/prefill-attribution.json")
    parser.add_argument("--corpora", nargs="+", choices=("trail", "telbench", "agentrx"), default=["trail", "telbench", "agentrx"])
    parser.add_argument("--max-cases", type=int); parser.add_argument("--max-tokens", type=int, default=1536)
    args = parser.parse_args(argv); work = Path(args.work); completed = load_completed(work)
    backend = QwenPrefillBackend(max_tokens=args.max_tokens); counts = {name: 0 for name in args.corpora}
    for corpus, identifier, steps, expected, base, ratio, limit in cases(args):
        if args.max_cases is not None and counts[corpus] >= args.max_cases: continue
        counts[corpus] += 1; key = corpus + ":" + identifier
        if key in completed and not completed[key].get("error"): continue
        started = time.perf_counter()
        try:
            last_error = None
            for prefix_chars, focus_chars in ((120, 480), (64, 240), (32, 120), (16, 64)):
                try:
                    predicted, evidence = attribute(steps, backend, symptom_ratio=ratio, max_candidates=limit,
                                                    prefix_chars=prefix_chars, focus_chars=focus_chars)
                    evidence["compression"] = {"prefix_chars": prefix_chars, "focus_chars": focus_chars}
                    break
                except ValueError as error:
                    if "above configured limit" not in str(error): raise
                    last_error = error
            else:
                raise last_error or ValueError("no compression configuration fit the model context")
            locations = [item.location for item in predicted]
            row = {"key": key, "corpus": corpus, "id": identifier, "expected": sorted(expected), "baseline": base,
                   "prefill": locations, "hybrid": safe_hybrid(base, locations, limit),
                   "seconds": time.perf_counter() - started, "input_tokens": evidence["input_tokens"],
                   "compression": evidence["compression"]}
        except Exception as error:
            row = {"key": key, "corpus": corpus, "id": identifier, "expected": sorted(expected), "baseline": base,
                   "prefill": [], "hybrid": base, "seconds": time.perf_counter() - started, "input_tokens": 0,
                   "error": f"{type(error).__name__}: {error}"}
        append(work, row); completed[key] = row; print(json.dumps({k: row[k] for k in ("key", "seconds", "error") if k in row}), flush=True)
    rows = list(completed.values()); report = {"method": "independent MASPrism paper-spec reproduction",
        "model": backend.model_id, "revision": backend.revision, "max_tokens": args.max_tokens,
        "hardware": {"platform": platform.platform(), "device": backend.device},
        "corpora": {name: summarize(rows, name) for name in args.corpora},
        "comparability": "Location-only scores; not TRAIL joint span+category accuracy."}
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
