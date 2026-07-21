"""Out-of-fold and leave-one-dataset-out diagnostic meta-ranker experiment."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from replayguard.claim_graph import diagnose_claim_graph
from replayguard.diagnosis import diagnose, load_ground_truth
from replayguard.diagnostic_candidates import DiagnosticCandidate, DiagnosticEvidence
from replayguard.diagnostic_corpora import load_agentrx, load_telbench, localization_metrics
from replayguard.invariants import inspect_run, inspect_semantic_spans, inspect_steps
from replayguard.hypothesis_verification import verify_hypotheses
from replayguard.meta_ranking import FEATURE_NAMES, candidate_feature_rows, rank_feature_rows
from replayguard.otel import import_traces
from replayguard.schema import Event, EventKind, Run, utcnow

SEED = 20260720


def text(value) -> str: return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def baseline(run: Run, limit=3):
    return [DiagnosticCandidate(item.span_id, item.category, item.score, "replayguard_baseline",
            (DiagnosticEvidence("RGBASE", item.reason, item.evidence),)) for item in diagnose(run, max_candidates=limit).suspects]


def event_steps(run: Run):
    return [(event.id, " ".join((f"kind={event.kind.value} name={event.name} status={event.status}",
             "request=" + text(event.request), "response=" + text(event.response), "error=" + text(event.error))))
            for event in sorted(run.events, key=lambda item: (item.started_at, item.id))]


def step_run(identifier, raw):
    run = Run(identifier)
    for index, row in enumerate(raw):
        location = str(row.get("index") or row.get("id") or index + 1)
        run.events.append(Event(EventKind.TOOL if str(row.get("role", "")).lower() == "tool" else EventKind.MODEL,
            str(row.get("role") or "step"), id=location, status="ok", ended_at=utcnow(), response=row.get("content")))
    return run


def make_case(dataset, identifier, steps, expected, base, invariant, gold_pairs=()):
    claims, _ = diagnose_claim_graph(steps, max_candidates=3)
    hypotheses, _, _ = verify_hypotheses(steps, max_candidates=8)
    rows = candidate_feature_rows(steps, baseline=base, invariants=invariant, claims=claims, hypotheses=hypotheses)
    for row in rows: row["label"] = int(row["location"] in expected)
    return {"dataset": dataset, "id": identifier, "expected": set(expected), "steps": list(steps),
            "gold_pairs": set(gold_pairs), "rows": rows,
            "signals": {"baseline": {x.location for x in base}, "invariants": {x.location for x in invariant},
                        "claim_graph": {x.location for x in claims}, "hypotheses": {x.location for x in hypotheses}}}


def load_cases(trail_root: Path, external: Path):
    result = []; manifest = json.loads((trail_root / "manifest.json").read_text(encoding="utf-8"))
    for record in manifest["records"]:
        run = import_traces(json.loads((trail_root / record["trace_path"]).read_text(encoding="utf-8")))[0]
        truth = load_ground_truth(trail_root / record["annotation_path"])
        from replayguard.diagnosis import normalize_category
        pairs = {(str(x.get("location")), normalize_category(x.get("category"))) for x in truth.get("errors", [])}
        expected = {location for location, _ in pairs}
        result.append(make_case("trail", record["trace_id"], event_steps(run), expected, baseline(run), inspect_run(run), pairs))
    for row in load_telbench(external / "telbench/TELBench.jsonl"):
        steps = [(span["id"], span["raw"]) for span in row["input"]["spans"]]
        raw = [{"id": a, "role": "assistant", "content": b} for a, b in steps]; run = step_run("tel:" + row["id"], raw)
        result.append(make_case("telbench", row["id"], steps, row["gold"], baseline(run), inspect_semantic_spans(row["input"]["spans"])))
    for row in load_agentrx(external / "agentrx"):
        raw = row["input"]["steps"]; steps = [(str(x.get("index") or i + 1), text(x.get("content"))) for i, x in enumerate(raw)]
        expected = {str(x["step"]) for x in row["gold"]}; run = step_run("rx:" + row["id"], raw)
        pairs = {(str(x["step"]), " ".join(str(x["category"]).lower().replace("/", " ").split())) for x in row["gold"]}
        result.append(make_case("agentrx", row["domain"] + ":" + row["id"], steps, expected, baseline(run), inspect_steps(raw), pairs))
    return result


def fold(identifier, folds=5): return int(hashlib.sha256(identifier.encode()).hexdigest()[:8], 16) % folds


def fit(cases):
    flat = [(case, row) for case in cases for row in case["rows"]]
    x = np.asarray([row["features"] for _, row in flat], dtype=float); y = np.asarray([row["label"] for _, row in flat])
    counts = Counter((case["dataset"], row["label"]) for case, row in flat)
    weights = np.asarray([1 / counts[(case["dataset"], row["label"])] for case, row in flat]); weights *= len(weights) / weights.sum()
    model = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000, random_state=SEED))
    model.fit(x, y, logisticregression__sample_weight=weights); return model


def predict(model, cases):
    output = {}
    for case in cases:
        if not case["rows"]:
            output[(case["dataset"], case["id"])] = set()
            continue
        probabilities = model.predict_proba(np.asarray([row["features"] for row in case["rows"]]))[:, 1]
        output[(case["dataset"], case["id"])] = set(rank_feature_rows(case["rows"], probabilities, limit=3))
    return output


def metrics(cases, predictions):
    return localization_metrics([(case["expected"], predictions[(case["dataset"], case["id"])]) for case in cases])


def signal_metrics(cases, name): return localization_metrics([(case["expected"], case["signals"][name]) for case in cases])


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--trail", default=".verify/upstream/trail-n2")
    parser.add_argument("--external", default=".verify/upstream/diagnostic-corpora")
    parser.add_argument("--output", default=".verify/reports/meta-ranker.json"); args = parser.parse_args(argv)
    cases = load_cases(Path(args.trail), Path(args.external)); datasets = ("trail", "telbench", "agentrx")
    oof = {}
    for held_fold in range(5):
        train = [c for c in cases if fold(c["dataset"] + ":" + c["id"]) != held_fold]
        test = [c for c in cases if fold(c["dataset"] + ":" + c["id"]) == held_fold]
        oof.update(predict(fit(train), test))
    transfer = {}
    for held in datasets:
        train = [c for c in cases if c["dataset"] != held]; test = [c for c in cases if c["dataset"] == held]
        transfer[held] = metrics(test, predict(fit(train), test))
    report = {"method": "15-feature logistic meta-ranker with error-first hypotheses", "features": FEATURE_NAMES,
        "candidate_limit": 3, "training": "trace-grouped five-fold OOF; per-dataset/per-class sample weighting",
        "datasets": {dataset: {"cases": sum(c["dataset"] == dataset for c in cases),
            "baseline": signal_metrics([c for c in cases if c["dataset"] == dataset], "baseline"),
            "invariants": signal_metrics([c for c in cases if c["dataset"] == dataset], "invariants"),
            "claim_graph": signal_metrics([c for c in cases if c["dataset"] == dataset], "claim_graph"),
            "hypotheses_top8": signal_metrics([c for c in cases if c["dataset"] == dataset], "hypotheses"),
            "candidate_union_oracle_recall": sum(len(c["expected"] & set().union(*c["signals"].values())) for c in cases if c["dataset"] == dataset) /
                                             sum(len(c["expected"]) for c in cases if c["dataset"] == dataset),
            "mixed_corpus_oof": metrics([c for c in cases if c["dataset"] == dataset], oof),
            "leave_one_dataset_out": transfer[dataset]} for dataset in datasets},
        "warning": "Location-only experiment; labels are used only by training folds and scoring."}
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
