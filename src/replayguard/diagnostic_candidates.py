"""Common candidate/evidence contract for composable diagnostic signals."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class DiagnosticEvidence:
    rule_id: str
    message: str
    excerpt: str = ""
    related_locations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DiagnosticCandidate:
    location: str
    category: str | None
    confidence: float
    signal_type: str
    evidence: tuple[DiagnosticEvidence, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.location:
            raise ValueError("candidate location must not be empty")
        if not 0 <= self.confidence <= 1:
            raise ValueError("candidate confidence must be between zero and one")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def merge_candidates(*groups: Iterable[DiagnosticCandidate], limit: int = 3) -> list[DiagnosticCandidate]:
    """Merge signals by location/category while retaining evidence and a strict candidate budget."""
    merged: dict[tuple[str, str | None], DiagnosticCandidate] = {}
    for group in groups:
        for item in group:
            key = (item.location, item.category); previous = merged.get(key)
            if previous is None:
                merged[key] = item
                continue
            evidence = tuple(dict.fromkeys((*previous.evidence, *item.evidence)))
            merged[key] = DiagnosticCandidate(item.location, item.category,
                max(previous.confidence, item.confidence),
                "+".join(dict.fromkeys((previous.signal_type, item.signal_type))), evidence)
    return sorted(merged.values(), key=lambda value: (-value.confidence, value.location, value.category or ""))[:limit]


def conservative_stack(primary: Iterable[DiagnosticCandidate], secondary: Iterable[DiagnosticCandidate],
                       *, limit: int = 3) -> list[DiagnosticCandidate]:
    """Preserve a calibrated primary ranking; enrich overlaps and fill only unused slots."""
    primary_rows = list(primary); secondary_rows = list(secondary); result = []
    for item in primary_rows:
        overlaps = [other for other in secondary_rows if other.location == item.location]
        evidence = tuple(dict.fromkeys((*item.evidence, *(e for other in overlaps for e in other.evidence))))
        signal = item.signal_type + ("+deterministic_invariant" if overlaps else "")
        result.append(DiagnosticCandidate(item.location, item.category, item.confidence, signal, evidence))
        if len(result) == limit: return result
    occupied = {(item.location, item.category) for item in result}
    for item in secondary_rows:
        if (item.location, item.category) not in occupied:
            result.append(item); occupied.add((item.location, item.category))
        if len(result) == limit: break
    return result
