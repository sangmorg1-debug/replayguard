"""Leakage-safe category assignment on TRAIL and AgentRx native taxonomies."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.pipeline import make_pipeline

from replayguard.category_assignment import assign_categories, category_training_rows
from replayguard.diagnostic_corpora import localization_metrics
from experiment_meta_ranker import SEED, fit, fold, load_cases, predict


def category_model():
    features = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=20000, sublinear_tf=True)
    return make_pipeline(features, SGDClassifier(loss="log_loss", max_iter=1000, tol=1e-4,
                                                  class_weight="balanced", random_state=SEED))


def evaluate(dataset: str, cases: list[dict], all_location_predictions: dict) -> dict:
    native = [case for case in cases if case["dataset"] == dataset]
    predicted_pairs: dict[tuple[str, str], set[tuple[str, str]]] = {}
    oracle_pairs: dict[tuple[str, str], set[tuple[str, str]]] = {}
    location_predictions: dict[tuple[str, str], set[str]] = {}
    for held_fold in range(5):
        category_train = [c for c in native if fold(c["dataset"] + ":" + c["id"]) != held_fold]
        category_test = [c for c in native if fold(c["dataset"] + ":" + c["id"]) == held_fold]
        texts, labels = category_training_rows(category_train)
        classifier = category_model().fit(texts, labels)
        for case in category_test:
            key = (dataset, case["id"]); guesses = all_location_predictions[key]
            location_predictions[key] = guesses
            predicted_pairs[key] = assign_categories(classifier, case["steps"], guesses)
            oracle_pairs[key] = assign_categories(classifier, case["steps"], case["expected"])
    joint_rows = [(case["gold_pairs"], predicted_pairs[(dataset, case["id"])]) for case in native]
    oracle_rows = [(case["gold_pairs"], oracle_pairs[(dataset, case["id"])]) for case in native]
    location_rows = [(case["expected"], location_predictions[(dataset, case["id"])]) for case in native]
    category_correct = sum(len(gold & guess) for gold, guess in oracle_rows)
    category_total = sum(len(gold) for gold, _ in oracle_rows)
    return {"cases": len(native), "taxonomy_labels": len({category for c in native for _, category in c["gold_pairs"]}),
            "location_top3": localization_metrics(location_rows),
            "oracle_location_category_accuracy": category_correct / category_total if category_total else 0.0,
            "end_to_end_joint": localization_metrics(joint_rows)}


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--trail", default=".verify/upstream/trail-n2")
    parser.add_argument("--external", default=".verify/upstream/diagnostic-corpora")
    parser.add_argument("--output", default=".verify/reports/category-assignment.json"); args = parser.parse_args(argv)
    cases = load_cases(Path(args.trail), Path(args.external))
    all_location_predictions = {}
    for held_fold in range(5):
        train = [c for c in cases if fold(c["dataset"] + ":" + c["id"]) != held_fold]
        test = [c for c in cases if fold(c["dataset"] + ":" + c["id"]) == held_fold]
        all_location_predictions.update(predict(fit(train), test))
    report = {"method": "trace-grouped five-fold OOF TF-IDF SGD log-loss category assigner",
              "trail": evaluate("trail", cases, all_location_predictions),
              "agentrx": evaluate("agentrx", cases, all_location_predictions),
              "telbench": {"status": "excluded", "reason": "TELBench has location labels but no failure taxonomy labels"},
              "warning": "Native taxonomies are trained and scored separately; oracle-location accuracy is not end-to-end accuracy."}
    target = Path(args.output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8"); print(json.dumps(report, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
