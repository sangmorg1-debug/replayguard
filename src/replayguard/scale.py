"""Streaming adapters and storage stress reporting for large public agent datasets."""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from .replay import ReplayMode, Replayer
from .schema import Event, EventKind, Run, utcnow
from .storage import LocalStore

SWE_BENCH_VERIFIED = {
    "dataset": "princeton-nlp/SWE-bench_Verified",
    "revision": "c104f840cc67f8b6eec6f759ebc8b2693d585d4a",
    "file": "data/test-00000-of-00001.parquet",
    "url": "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/resolve/c104f840cc67f8b6eec6f759ebc8b2693d585d4a/data/test-00000-of-00001.parquet",
    "sha256": "a45b1fe4e2f0c8390b2b2938ac83e92ed5979000856808f3679c07812e9e6dcd",
    "records": 500,
}


def _finish(run: Run) -> Run:
    run.status = "ok"; run.ended_at = utcnow(); return run


def swe_bench_run(row: dict[str, Any]) -> Run:
    instance = str(row["instance_id"])
    run = Run(f"swe-bench-verified:{instance}", id=f"swe-bench-verified-{instance}", attributes={
        "dataset": "SWE-bench Verified", "dataset_revision": SWE_BENCH_VERIFIED["revision"],
        "instance_id": instance, "repository": row.get("repo"), "base_commit": row.get("base_commit"),
        "difficulty": row.get("difficulty"), "environment_setup_commit": row.get("environment_setup_commit"),
    })
    run.events.append(Event(EventKind.CONVERSATION, "github.issue", status="ok", ended_at=utcnow(),
                            request={"problem_statement": row.get("problem_statement", ""), "hints": row.get("hints_text", "")}))
    run.events.append(Event(EventKind.ARTIFACT, "gold.patch", status="ok", ended_at=utcnow(), response=row.get("patch", ""),
                            attributes={"role": "reference_only", "must_not_leak_to_candidate": True}))
    run.events.append(Event(EventKind.ARTIFACT, "test.patch", status="ok", ended_at=utcnow(), response=row.get("test_patch", ""),
                            attributes={"role": "evaluation"}))
    run.events.append(Event(EventKind.EVALUATION, "swe-bench.tests", status="ok", ended_at=utcnow(), request={
        "fail_to_pass": _json_list(row.get("FAIL_TO_PASS")), "pass_to_pass": _json_list(row.get("PASS_TO_PASS"))},
        response={"execution": "not_run", "fixture": "verified task metadata"}))
    return _finish(run)


def iter_swe_bench(path: str | Path, *, batch_size: int = 32) -> Iterator[Run]:
    source = Path(path)
    if source.suffix.lower() in {".jsonl", ".ndjson"}:
        with source.open(encoding="utf-8") as rows:
            for line in rows:
                if line.strip(): yield swe_bench_run(json.loads(line))
        return
    if source.suffix.lower() != ".parquet": raise ValueError("SWE-bench input must be parquet or JSONL")
    try:
        import pyarrow.parquet as parquet
    except ImportError as exc:
        raise RuntimeError("parquet ingestion requires `pip install replayguard[scale]`") from exc
    reader = parquet.ParquetFile(source)
    for batch in reader.iter_batches(batch_size=batch_size):
        for row in batch.to_pylist(): yield swe_bench_run(row)


def iter_tau2(path: str | Path) -> Iterator[Run]:
    source = Path(path)
    paths = sorted(source.rglob("*.json")) if source.is_dir() else [source]
    for item in paths:
        try: value = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError): continue
        records = value.get("simulations") if isinstance(value, dict) else None
        if isinstance(records, list):
            for record in records:
                if isinstance(record, dict): yield tau2_run(record, item)
        elif isinstance(value, dict) and ("ticks" in value or "messages" in value or "trajectory" in value):
            yield tau2_run(value, item)


def tau2_run(row: dict[str, Any], source: Path | None = None) -> Run:
    identity = str(row.get("id") or row.get("simulation_id") or row.get("task_id") or hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()[:16])
    if isinstance(row.get("ticks"), list):
        run = Run(f"tau2-voice:{identity}", id=identity, created_at=str(row.get("start_time") or utcnow()),
                  ended_at=row.get("end_time"), status="ok", attributes={"dataset": "tau2-bench simulation",
                  "task_id": row.get("task_id"), "trial": row.get("trial"), "seed": row.get("seed"),
                  "mode": row.get("mode"), "termination_reason": row.get("termination_reason"),
                  "duration_seconds": row.get("duration")})
        for tick in row["ticks"]:
            for side in ("agent_chunk", "user_chunk"):
                chunk = tick.get(side) if isinstance(tick, dict) else None
                if chunk and (chunk.get("contains_speech") or chunk.get("turn_taking_action")):
                    timestamp = str(tick.get("timestamp") or utcnow())
                    run.events.append(Event(EventKind.AGENT_STEP, f"voice.{chunk.get('role', side)}", started_at=timestamp,
                                            ended_at=timestamp, status="ok", response=chunk,
                                            attributes={"tick_id": tick.get("tick_id"), "recorded": True}))
        return run
    run = Run(f"tau2-trajectory:{identity}", id=f"tau2-{identity}", created_at=str(row.get("start_time") or utcnow()),
              attributes={"dataset": "tau2-bench trajectory", "task_id": row.get("task_id"), "reward": row.get("reward")})
    messages = row.get("messages") or row.get("trajectory") or []
    for index, message in enumerate(messages):
        if not isinstance(message, dict): continue
        role = str(message.get("role") or message.get("source") or "unknown")
        tool = message.get("tool_name") or message.get("name") if role in {"tool", "assistant/tool"} else None
        kind = EventKind.TOOL if tool else EventKind.CONVERSATION
        run.events.append(Event(kind, str(tool or f"message.{role}"), status="ok", ended_at=utcnow(),
                                request=message.get("arguments") if tool else None, response=message.get("content") or message.get("result"),
                                attributes={"sequence": index, "role": role, "recorded": True}))
    return _finish(run)


def ingest(runs: Iterable[Run], store: LocalStore, *, dataset: str, manifest_path: str | Path,
           max_runs: int | None = None, replay_sample: int = 25) -> dict[str, Any]:
    started = time.perf_counter(); ids = []; events = 0; logical_bytes = 0
    for run in runs:
        if max_runs is not None and len(ids) >= max_runs: break
        raw = json.dumps(run.to_dict(), ensure_ascii=False, separators=(",", ":")).encode()
        store.save_run(run); ids.append(run.id); events += len(run.events); logical_bytes += len(raw)
    ingest_seconds = time.perf_counter() - started
    replay_started = time.perf_counter(); replay_events = 0
    for run_id in ids[:replay_sample]:
        source = store.load_run(run_id); result = Replayer().replay(source, mode=ReplayMode.EXACT)
        if result.live_calls: raise AssertionError("scale replay unexpectedly made a live call")
        replay_events += result.fixture_hits
    replay_seconds = time.perf_counter() - replay_started
    report: dict[str, Any] = {"format": "replayguard-scale-ingest-v1", "dataset": dataset, "runs": len(ids),
        "events": events, "logical_bytes": logical_bytes, "ingest_seconds": ingest_seconds,
        "runs_per_second": len(ids) / ingest_seconds if ingest_seconds else 0, "replay_sample_runs": min(replay_sample, len(ids)),
        "replay_sample_events": replay_events, "replay_seconds": replay_seconds, "run_ids": ids}
    report["report_sha256"] = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    target = Path(manifest_path); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list): return value
    try: parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError): return []
    return parsed if isinstance(parsed, list) else []
