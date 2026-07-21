"""Leakage-safe readers and common localization scoring for external corpora."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

ROOTSE_REVISION = "c3e54cf25f99eddd85d8c9cbe3f41528e5e7f957"


def load_telbench(path: str | Path) -> Iterator[dict]:
    """Yield model input separately from held-back span-level gold labels."""
    with Path(path).open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line); spans = row.get("spans", [])
            yield {
                "id": str(row["id"]),
                "input": {"question": str(row.get("question", "")), "spans": [
                    {"id": str(span.get("id") or span.get("span_id")),
                     "raw": str(span.get("raw") or span.get("span_text") or "")}
                    for span in spans
                ]},
                "gold": {str(value) for value in row.get("gold", {}).get("error_span_ids", [])},
                "meta": dict(row.get("meta", {})),
            }


def load_agentrx(corpus_root: str | Path) -> Iterator[dict]:
    """Join AgentRx trajectories to human step/category labels without renumbering steps."""
    root = Path(corpus_root)
    tau_rows = json.loads((root / "data/tau_retail/tau_dataset_failed.json").read_text(encoding="utf-8"))
    tau = {str(row["task_id"]): row for row in tau_rows}
    yield from _join_agentrx("tau", tau, root / "data/ground_truth/tau_ground_truth.json")
    mag_dir = root / "data/magentic_dataset"
    mag = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in mag_dir.glob("*.json")
           if path.name not in {"magentic_count.json", "steps_by_id.json"}}
    yield from _join_agentrx("magentic-one", mag, root / "data/ground_truth/magentic_one_ground_truth.json")


def load_rootse(corpus_root: str | Path) -> Iterator[dict]:
    """Yield RootSE trace inputs separately from earliest-error gold labels."""
    root = Path(corpus_root)
    for path in sorted((root / "data").rglob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8")); steps = []
        for offset, step in enumerate(row.get("original_traj", [])):
            location = str(step.get("index", offset))
            pieces = [str(step.get(name, "")) for name in ("thought", "response", "action", "observation")]
            steps.append({"id": location, "raw": "\n".join(piece for piece in pieces if piece)})
        failure = str(row["failure_id"])
        if failure not in {step["id"] for step in steps}:
            raise ValueError(f"RootSE failure_id is not a trajectory step: {path.name}:{failure}")
        trajectory_id = path.relative_to(root / "data").as_posix().removesuffix(".json")
        yield {"id": trajectory_id, "input": {"steps": steps}, "gold": {failure},
               "meta": {"agent": str(row.get("agent", "")), "model": str(row.get("model", "")),
                        "repo": str(row.get("repo", "")), "language": str(row.get("repo_language", "")),
                        "instance_id": str(row["instance_id"])},
               "failure_reason": str(row.get("failure_reason", ""))}


def _join_agentrx(domain: str, trajectories: dict[str, dict], truth_path: Path) -> Iterator[dict]:
    for label in json.loads(truth_path.read_text(encoding="utf-8")):
        identifier = str(label["trajectory_id"]); trajectory = trajectories.get(identifier)
        if trajectory is None:
            raise ValueError(f"AgentRx ground truth has no trajectory: {domain}:{identifier}")
        if isinstance(trajectory, list):
            steps = trajectory
        elif isinstance(trajectory, dict):
            steps = trajectory.get("traj") or trajectory.get("trajectory") or trajectory.get("messages") or []
        else:
            raise ValueError(f"unsupported AgentRx trajectory shape: {domain}:{identifier}")
        failures = [{"step": int(item["step_number"]), "category": str(item["failure_category"]),
                     "agent": str(item.get("failed_agent", "")), "reason": str(item.get("step_reason", ""))}
                    for item in label.get("failures", [])]
        yield {"id": identifier, "domain": domain, "input": {"steps": steps}, "gold": failures,
               "root_failure_id": label.get("root_cause", {}).get("failure_id")}


def localization_metrics(rows: list[tuple[set[str | int], set[str | int]]]) -> dict:
    matched = sum(len(gold & predicted) for gold, predicted in rows)
    expected = sum(len(gold) for gold, _ in rows); predicted = sum(len(value) for _, value in rows)
    precision = matched / predicted if predicted else 0.0
    recall = matched / expected if expected else 0.0
    macro = sum(len(gold & guess) / len(gold) if gold else float(not guess) for gold, guess in rows) / len(rows) if rows else 0.0
    return {"cases": len(rows), "expected": expected, "predicted": predicted, "matched": matched,
            "precision": precision, "micro_recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "macro_recall": macro}
