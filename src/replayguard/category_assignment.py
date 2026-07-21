"""Utilities for assigning native failure taxonomies to localized trace steps."""
from __future__ import annotations

from collections.abc import Iterable, Sequence


def category_training_rows(
    cases: Iterable[dict],
) -> tuple[list[str], list[str]]:
    """Extract text/category examples from gold training traces only.

    The caller owns the train/test split. Keeping extraction here makes it harder for
    experiment code to accidentally use labels from a held-out trace as features.
    """
    texts: list[str] = []
    labels: list[str] = []
    for case in cases:
        by_location = dict(case["steps"])
        for location, category in case.get("gold_pairs", set()):
            value = by_location.get(location)
            if value is not None and category:
                texts.append(value[:4000])
                labels.append(category)
    return texts, labels


def assign_categories(model, steps: Sequence[tuple[str, str]], locations: Iterable[str]) -> set[tuple[str, str]]:
    """Assign exactly one category to each proposed location."""
    by_location = dict(steps)
    ordered = [str(location) for location in locations if str(location) in by_location]
    if not ordered:
        return set()
    labels = model.predict([by_location[location][:4000] for location in ordered])
    return set(zip(ordered, (str(label) for label in labels)))
