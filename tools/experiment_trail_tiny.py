"""Leakage-resistant tiny local model experiment on the gated TRAIL corpus.

The primary result is five-fold out-of-fold prediction grouped by complete trace. Features never
include Event.attributes or preserved raw spans because gated TRAIL embeds annotation metadata there.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.multiclass import OneVsRestClassifier

from replayguard.diagnosis import CATEGORIES, diagnose, load_ground_truth, normalize_category
from replayguard.otel import import_traces

SEED = 20260720
MODEL_SPEC = {
    "family": "TF-IDF word 1-2 grams + one-vs-rest logistic SGD",
    "max_features": 30_000, "min_df": 2, "alpha": 1e-5, "candidate_limit": 3,
    "feature_request_tail_chars": 2_500, "feature_response_tail_chars": 6_000,
    "feature_error_tail_chars": 1_000,
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assign_fold(trace_id: str, folds: int) -> int:
    return int(hashlib.sha256(trace_id.encode()).hexdigest()[:8], 16) % folds


def clipped(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[-limit:]


def event_features(event, index: int, total: int) -> str:
    """Build features from canonical safe fields only; never inspect attributes/raw annotations."""
    return " ".join((f"name {event.name}", f"kind {event.kind.value}", f"status {event.status}",
                     f"position {index}/{total}", f"has_parent {bool(event.parent_id)}",
                     "request " + clipped(event.request, MODEL_SPEC["feature_request_tail_chars"]),
                     "response " + clipped(event.response, MODEL_SPEC["feature_response_tail_chars"]),
                     "error " + clipped(event.error, MODEL_SPEC["feature_error_tail_chars"])))


def load_corpus(root: Path) -> tuple[list[dict], dict]:
    manifest_path = root / "manifest.json"; manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    traces = []
    for record in manifest["records"]:
        trace_path, annotation_path = root / record["trace_path"], root / record["annotation_path"]
        if digest(trace_path) != record["trace_sha256"]: raise ValueError(f"trace checksum drift: {record['trace_path']}")
        if digest(annotation_path) != record["annotation_sha256"]: raise ValueError(f"annotation checksum drift: {record['annotation_path']}")
        run = import_traces(json.loads(trace_path.read_text(encoding="utf-8")))[0]
        truth = load_ground_truth(annotation_path)
        expected = {(str(item.get("location")), normalize_category(item.get("category")))
                    for item in truth.get("errors", [])}
        rows = [{"span_id": event.id, "text": event_features(event, index, len(run.events)),
                 "labels": [int((event.id, category) in expected) for category in CATEGORIES]}
                for index, event in enumerate(run.events)]
        traces.append({"trace_id": record["trace_id"], "domain": record["split"],
                       "expected": expected, "rows": rows, "run": run})
    return traces, {"repository": manifest["repository"], "revision": manifest["revision"],
                    "manifest_sha256": digest(manifest_path), "trace_count": len(traces),
                    "span_count": sum(len(item["rows"]) for item in traces)}


def fit(train: list[dict]):
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=MODEL_SPEC["min_df"], max_df=.98,
                                 max_features=MODEL_SPEC["max_features"], sublinear_tf=True,
                                 strip_accents="unicode")
    x = vectorizer.fit_transform([row["text"] for trace in train for row in trace["rows"]])
    y = np.asarray([row["labels"] for trace in train for row in trace["rows"]])
    classifier = OneVsRestClassifier(SGDClassifier(loss="log_loss", class_weight="balanced",
        alpha=MODEL_SPEC["alpha"], max_iter=1_000, tol=1e-3, random_state=SEED), n_jobs=-1)
    classifier.fit(x, y)
    return vectorizer, classifier


def model_candidates(vectorizer, classifier, trace: dict, limit: int = 3) -> list[tuple[str, str]]:
    rows = trace["rows"]; scores = classifier.decision_function(vectorizer.transform([row["text"] for row in rows]))
    ranked = sorted(((float(scores[i, j]), rows[i]["span_id"], category)
                     for i in range(len(rows)) for j, category in enumerate(CATEGORIES)), reverse=True)
    return [(span_id, category) for _, span_id, category in ranked[:limit]]


def hybrid_candidates(model: list[tuple[str, str]], trace: dict, limit: int = 3) -> list[tuple[str, str]]:
    result = list(model[:max(0, limit - 1)])
    for item in diagnose(trace["run"], max_candidates=limit).suspects:
        pair = (item.span_id, item.category)
        if pair not in result: result.append(pair)
        if len(result) == limit: break
    for pair in model:
        if pair not in result: result.append(pair)
        if len(result) == limit: break
    return result


def metrics(predictions: list[dict]) -> dict:
    expected = sum(len(item["expected"]) for item in predictions)
    predicted = sum(len(item["predicted"]) for item in predictions)
    matched = sum(len(item["expected"] & item["predicted"]) for item in predictions)
    precision = matched / predicted if predicted else 0.0; recall = matched / expected if expected else 0.0
    per_trace = [len(item["expected"] & item["predicted"]) / len(item["expected"])
                 if item["expected"] else 0.0 for item in predictions]
    generator = random.Random(SEED); size = len(per_trace)
    boot = sorted(sum(generator.choice(per_trace) for _ in range(size)) / size for _ in range(10_000)) if size else [0.0]
    return {"traces": len(predictions), "expected_pairs": expected, "predicted_pairs": predicted,
            "matched_pairs": matched, "pair_precision": precision, "micro_pair_recall": recall,
            "pair_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "official_macro_joint_accuracy": sum(per_trace) / size if size else 0.0,
            "macro_95pct_trace_bootstrap": [boot[int(len(boot) * .025)], boot[int(len(boot) * .975)]]}


def write_official(predictions: list[dict], root: Path) -> None:
    for item in predictions:
        folder = root / item["domain"].replace(" ", "_")
        folder.mkdir(parents=True, exist_ok=True)
        errors = [{"location": span, "category": category} for span, category in sorted(item["predicted"])]
        (folder / f"{item['trace_id']}.json").write_text(json.dumps({"errors": errors}, indent=2) + "\n", encoding="utf-8")


def evaluate_folds(traces: list[dict], folds: int) -> tuple[list[dict], list[dict], list[dict]]:
    model_output, hybrid_output, fold_evidence = [], [], []
    for fold in range(folds):
        train = [item for item in traces if assign_fold(item["trace_id"], folds) != fold]
        test = [item for item in traces if assign_fold(item["trace_id"], folds) == fold]
        started = time.perf_counter(); vectorizer, classifier = fit(train); trained = time.perf_counter() - started
        predict_started = time.perf_counter()
        for trace in test:
            model = model_candidates(vectorizer, classifier, trace, MODEL_SPEC["candidate_limit"])
            common = {"trace_id": trace["trace_id"], "domain": trace["domain"], "expected": trace["expected"]}
            model_output.append({**common, "predicted": set(model)})
            hybrid_output.append({**common, "predicted": set(hybrid_candidates(model, trace, MODEL_SPEC["candidate_limit"]))})
        elapsed = time.perf_counter() - predict_started
        coefficients = sum(estimator.coef_.size for estimator in classifier.estimators_ if hasattr(estimator, "coef_"))
        fold_evidence.append({"fold": fold, "train_traces": len(train), "test_traces": len(test),
                              "vocabulary_features": len(vectorizer.vocabulary_), "linear_coefficients": coefficients,
                              "train_seconds": trained, "prediction_seconds": elapsed,
                              "milliseconds_per_trace": elapsed * 1000 / len(test)})
    return model_output, hybrid_output, fold_evidence


def domain_transfer(traces: list[dict]) -> dict:
    report = {}
    for train_domain, test_domain in (("GAIA", "SWE Bench"), ("SWE Bench", "GAIA")):
        train = [item for item in traces if item["domain"] == train_domain]
        test = [item for item in traces if item["domain"] == test_domain]
        started = time.perf_counter(); vectorizer, classifier = fit(train)
        output = []
        for trace in test:
            predicted = set(model_candidates(vectorizer, classifier, trace, MODEL_SPEC["candidate_limit"]))
            output.append({"trace_id": trace["trace_id"], "domain": test_domain,
                           "expected": trace["expected"], "predicted": predicted})
        report[f"{train_domain}_to_{test_domain}"] = {**metrics(output), "train_seconds": time.perf_counter() - started}
    return report


def safe_json(value: Any) -> Any:
    if isinstance(value, set): return [list(item) for item in sorted(value)]
    raise TypeError(type(value).__name__)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--corpus", type=Path, default=Path(".verify/upstream/trail-hf"))
    parser.add_argument("--output", type=Path, default=Path(".verify/trail-tiny-experiment")); parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args(argv)
    if args.folds < 2: parser.error("--folds must be at least 2")
    traces, corpus = load_corpus(args.corpus); args.output.mkdir(parents=True, exist_ok=True)
    model, hybrid, folds = evaluate_folds(traces, args.folds)
    deterministic = [{"trace_id": trace["trace_id"], "domain": trace["domain"], "expected": trace["expected"],
        "predicted": {(item.span_id, item.category) for item in diagnose(trace["run"]).suspects}} for trace in traces]
    report = {"experiment_version": "trail-tiny-v1", "seed": SEED, "model_spec": MODEL_SPEC,
              "corpus": corpus, "leakage_controls": {
                  "unit_of_split": "complete trace", "out_of_fold_predictions_only": True,
                  "event_attributes_used": False, "raw_spans_used": False, "annotation_paths_used_as_features": False,
                  "warning": "The public benchmark was previously inspected; cross-validation is not a hidden leaderboard."},
              "primary_out_of_fold_tiny_model": metrics(model),
              "frozen_deterministic_baseline": metrics(deterministic),
              "exploratory_hybrid": metrics(hybrid), "domain_transfer": domain_transfer(traces),
              "fold_evidence": folds, "runtime": {"python": sys.version.split()[0], "sklearn": sklearn.__version__,
                                                    "platform": platform.platform(), "accelerator_required": False}}
    write_official(model, args.output / "official_predictions" / "tiny_model")
    write_official(deterministic, args.output / "official_predictions" / "deterministic")
    write_official(hybrid, args.output / "official_predictions" / "hybrid")
    target = args.output / "report.json"; target.write_text(json.dumps(report, indent=2, default=safe_json) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(target.resolve()), "tiny_model": report["primary_out_of_fold_tiny_model"],
                      "deterministic": report["frozen_deterministic_baseline"], "hybrid": report["exploratory_hybrid"],
                      "domain_transfer": report["domain_transfer"]}, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
