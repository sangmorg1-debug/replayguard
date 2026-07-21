"""Adapters for public agent/tool benchmark data used by the real-data suite."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterator

from .schema import Event, EventKind, Run, utcnow


def _finish(run: Run) -> Run:
    run.status = "ok"
    run.ended_at = utcnow()
    return run


def load_bfcl(cases_path: str | Path, answers_path: str | Path) -> Iterator[Run]:
    answers = {row["id"]: row["ground_truth"] for row in _jsonl(answers_path)}
    for case in _jsonl(cases_path):
        run = Run(f"bfcl:{case['id']}", attributes={"dataset": "BFCL-v4", "case_id": case["id"]})
        run.events.append(Event(EventKind.CONVERSATION, "user.request", status="ok", ended_at=utcnow(),
                                request=case["question"]))
        for tool in case.get("function", []):
            run.events.append(Event(EventKind.TOOL_PROPOSAL, tool["name"], status="ok", ended_at=utcnow(),
                                    request=tool.get("parameters"), attributes={"description": tool.get("description", "")}))
        for expected in answers.get(case["id"], []):
            for name, arguments in expected.items():
                run.events.append(Event(EventKind.TOOL, name, status="ok", ended_at=utcnow(),
                                        request=arguments, response={"fixture": True}, attributes={"ground_truth": True}))
        yield _finish(run)


def load_tau_tasks(path: str | Path) -> Iterator[Run]:
    for task in json.loads(Path(path).read_text(encoding="utf-8")):
        run = Run(f"tau2:airline:{task['id']}", attributes={"dataset": "tau2-bench", "case_id": task["id"]})
        scenario = task.get("user_scenario", {}).get("instructions", {})
        run.events.append(Event(EventKind.CONVERSATION, "user.scenario", status="ok", ended_at=utcnow(), request=scenario))
        criteria = task.get("evaluation_criteria", {})
        for action in criteria.get("actions", []):
            name = action.get("name") or action.get("action") or "expected.action"
            run.events.append(Event(EventKind.TOOL, name, status="ok", ended_at=utcnow(), request=action,
                                    response={"fixture": True}, attributes={"ground_truth": True}))
        run.events.append(Event(EventKind.EVALUATION, "tau2.criteria", status="ok", ended_at=utcnow(),
                                request=criteria, response={"reward_basis": criteria.get("reward_basis", [])}))
        yield _finish(run)


def load_agentdojo_vectors(path: str | Path) -> Iterator[Run]:
    """Parse the intentionally simple vector registry without a YAML dependency."""
    text = Path(path).read_text(encoding="utf-8")
    keys = re.findall(r"(?m)^([a-z][a-z0-9_]+):\s*$", text)
    defaults = re.findall(r'(?m)^\s+default:\s+["\']?(.*?)["\']?\s*$', text)
    for index, key in enumerate(keys):
        run = Run(f"agentdojo:{key}", attributes={"dataset": "AgentDojo", "vector": key})
        content = defaults[index] if index < len(defaults) else ""
        run.events.append(Event(EventKind.RETRIEVAL, "untrusted.content", status="ok", ended_at=utcnow(), response=content,
                                attributes={"trust": "untrusted", "injection_vector": key}))
        run.events.append(Event(EventKind.AUTHORIZATION, "indirect_prompt_injection.boundary", status="ok", ended_at=utcnow(),
                                request={"source": key}, response={"decision": "requires_policy"}))
        yield _finish(run)


def load_openai_preferences(path: str | Path) -> Iterator[Run]:
    """Load real model summaries and crowd-worker pairwise choices."""
    for index, row in enumerate(_jsonl(path)):
        summaries = row["summaries"]
        choice = int(row["choice"])
        run = Run(f"openai-preference:{row.get('batch')}:{index}", attributes={
            "dataset": "OpenAI summarize-from-feedback", "split": row.get("split"),
            "worker": row.get("worker"), "human_choice": choice,
            "confidence": row.get("extra", {}).get("confidence"),
        })
        run.events.append(Event(EventKind.CONVERSATION, "source.document", status="ok", ended_at=utcnow(), request=row["info"]))
        for candidate_index, summary in enumerate(summaries):
            run.events.append(Event(EventKind.ARTIFACT, f"summary.candidate.{candidate_index}", status="ok", ended_at=utcnow(),
                                    response=summary["text"], attributes={"policy": summary.get("policy"), "candidate": candidate_index}))
        run.events.append(Event(EventKind.EVALUATION, "human.pairwise_preference", status="ok", ended_at=utcnow(),
                                request={"candidates": len(summaries)}, response={"choice": choice},
                                attributes={"evaluator": "crowd_worker", "confidence": row.get("extra", {}).get("confidence")}))
        yield _finish(run)


def load_tau_voice_trace(path: str | Path) -> Run:
    """Load a real recorded tau2 full-duplex simulation at tick granularity."""
    row = json.loads(Path(path).read_text(encoding="utf-8"))
    run = Run(f"tau2-voice:{row['id']}", id=row["id"], created_at=row["start_time"], ended_at=row["end_time"],
              status="ok", attributes={"dataset": "tau2-bench simulation", "task_id": row["task_id"],
              "trial": row["trial"], "seed": row["seed"], "mode": row["mode"],
              "termination_reason": row["termination_reason"], "duration_seconds": row["duration"]})
    for tick in row["ticks"]:
        for side in ("agent_chunk", "user_chunk"):
            chunk = tick.get(side)
            if chunk and (chunk.get("contains_speech") or chunk.get("turn_taking_action")):
                run.events.append(Event(EventKind.AGENT_STEP, f"voice.{chunk['role']}", started_at=tick["timestamp"],
                                        ended_at=tick["timestamp"], status="ok", response=chunk,
                                        attributes={"tick_id": tick["tick_id"], "recorded": True}))
    return run


def _jsonl(path: str | Path) -> Iterator[dict]:
    with Path(path).open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                yield json.loads(line)
