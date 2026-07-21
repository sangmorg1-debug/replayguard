"""Label-free feature construction for calibrated diagnostic candidate routing."""
from __future__ import annotations

import math
import re
from typing import Iterable, Sequence

from .diagnostic_candidates import DiagnosticCandidate

ERROR = re.compile(r"(?i)\b(error|exception|failed|failure|invalid|timeout|not found|forbidden|unauthorized)\b")
COMMITMENT = re.compile(r"(?i)\b(final answer|therefore|conclude|confirmed|verified|the answer is|cannot determine|unable to)\b")
FEATURE_NAMES = (
    "baseline_score", "baseline_reciprocal_rank", "invariant_score", "invariant_reciprocal_rank",
    "claim_score", "claim_reciprocal_rank", "signal_agreement", "position", "is_last",
    "hypothesis_score", "hypothesis_reciprocal_rank", "log_text_chars", "explicit_error", "commitment", "related_evidence_count",
)


def candidate_feature_rows(steps: Sequence[tuple[str, str]], *, baseline: Iterable[DiagnosticCandidate],
                           invariants: Iterable[DiagnosticCandidate], claims: Iterable[DiagnosticCandidate],
                           hypotheses: Iterable[DiagnosticCandidate] = ()) -> list[dict]:
    groups = {"baseline": list(baseline), "invariant": list(invariants), "claim": list(claims),
              "hypothesis": list(hypotheses)}
    by_location = {location: (index, text) for index, (location, text) in enumerate(steps)}
    locations = sorted({item.location for rows in groups.values() for item in rows},
                       key=lambda location: by_location.get(location, (len(steps), ""))[0])
    maps = {name: {item.location: (item, rank) for rank, item in enumerate(rows, 1)} for name, rows in groups.items()}
    result = []
    for location in locations:
        index, text = by_location.get(location, (len(steps), "")); entries = [maps[name].get(location) for name in groups]
        related = sum(len(evidence.related_locations) for entry in entries if entry for evidence in entry[0].evidence)
        features = (
            maps["baseline"].get(location, (None, 0))[0].confidence if location in maps["baseline"] else 0.0,
            1 / maps["baseline"][location][1] if location in maps["baseline"] else 0.0,
            maps["invariant"].get(location, (None, 0))[0].confidence if location in maps["invariant"] else 0.0,
            1 / maps["invariant"][location][1] if location in maps["invariant"] else 0.0,
            maps["claim"].get(location, (None, 0))[0].confidence if location in maps["claim"] else 0.0,
            1 / maps["claim"][location][1] if location in maps["claim"] else 0.0,
            sum(entry is not None for entry in entries),
            index / max(1, len(steps) - 1), float(index == len(steps) - 1),
            maps["hypothesis"].get(location, (None, 0))[0].confidence if location in maps["hypothesis"] else 0.0,
            1 / maps["hypothesis"][location][1] if location in maps["hypothesis"] else 0.0,
            math.log1p(len(text)), float(bool(ERROR.search(text))), float(bool(COMMITMENT.search(text))), related,
        )
        result.append({"location": location, "features": features})
    return result


def rank_feature_rows(rows: list[dict], probabilities: Sequence[float], *, limit: int = 3) -> list[str]:
    paired = sorted(zip(probabilities, rows), key=lambda pair: (-float(pair[0]), pair[1]["location"]))
    return [row["location"] for _, row in paired[:limit]]
