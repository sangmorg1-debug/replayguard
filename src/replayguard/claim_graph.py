"""Training-free claim/evidence graph for local failure-location routing."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from .diagnostic_candidates import DiagnosticCandidate, DiagnosticEvidence

WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{2,}")
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
COMMIT = re.compile(r"(?i)\b(final answer|therefore|thus|conclude|confirmed|verified|we found|i found|the answer is|cannot determine|unable to|no answer|must be|is the correct)\b")
FINAL = re.compile(r"(?i)\b(final answer|the answer is|conclude|cannot determine|unable to|no answer)\b")
EXPLORATORY = re.compile(r"(?i)^(search|query|find|look up|investigate|try|check)\b|\?$|\b(maybe|possibly|candidate|might)\b")
EVIDENCE = re.compile(r"(?i)\b(source|result|returned|shows|states|according|documentation|record|output|evidence|found)\b")
STOP = {"the", "and", "that", "this", "with", "from", "have", "will", "into", "your", "their", "there", "then",
        "than", "were", "been", "being", "about", "would", "could", "should", "which", "what", "when", "where", "because"}


@dataclass(frozen=True, slots=True)
class ClaimNode:
    claim_id: str
    location: str
    text: str
    terms: frozenset[str]
    finalized: bool


@dataclass(frozen=True, slots=True)
class SupportEdge:
    source_location: str
    claim_id: str
    strength: float


@dataclass(frozen=True, slots=True)
class ClaimGraph:
    claims: tuple[ClaimNode, ...]
    support: tuple[SupportEdge, ...]
    reuse: tuple[tuple[str, str], ...]  # claim id -> later location


def terms(text: str) -> frozenset[str]:
    return frozenset(word.lower() for word in WORD.findall(text) if word.lower() not in STOP)


def similarity(left: frozenset[str], right: frozenset[str], frequencies: Counter[str]) -> float:
    if not left or not right: return 0.0
    common = left & right
    # Stable summation order matters near thresholds and for downstream learned ranking.
    # Iterating a frozenset made predictions depend on Python's per-process hash seed.
    numerator = math.fsum(1 / math.sqrt(max(1, frequencies[word])) for word in sorted(common))
    denominator = math.sqrt(len(left) * len(right))
    return numerator / denominator if denominator else 0.0


def build_claim_graph(steps: Sequence[tuple[str, str]]) -> ClaimGraph:
    span_terms = [terms(text) for _, text in steps]; frequencies = Counter(word for row in span_terms for word in row)
    claims = []
    for index, (location, text) in enumerate(steps):
        sentences = [part.strip() for part in SENTENCE.split(text) if part.strip()]
        selected = [sentence for sentence in sentences if COMMIT.search(sentence) and not EXPLORATORY.search(sentence)]
        if index == len(steps) - 1 and not selected and sentences:
            selected = [sentences[-1]]
        for sentence in selected[:2]:
            claims.append(ClaimNode(f"c{len(claims) + 1}", location, sentence[:1000], terms(sentence), bool(FINAL.search(sentence) or index == len(steps) - 1)))
    support = []; reuse = []
    location_index = {location: index for index, (location, _) in enumerate(steps)}
    for claim in claims:
        claim_index = location_index[claim.location]
        for index in range(claim_index):
            if EXPLORATORY.search(steps[index][1].strip()):
                continue
            strength = similarity(claim.terms, span_terms[index], frequencies)
            if EVIDENCE.search(steps[index][1]): strength *= 1.2
            if strength >= .08: support.append(SupportEdge(steps[index][0], claim.claim_id, min(1.0, strength)))
        for index in range(claim_index + 1, len(steps)):
            if similarity(claim.terms, span_terms[index], frequencies) >= .12:
                reuse.append((claim.claim_id, steps[index][0]))
    return ClaimGraph(tuple(claims), tuple(support), tuple(reuse))


def diagnose_claim_graph(steps: Sequence[tuple[str, str]], *, max_candidates: int = 3,
                         support_threshold: float = .16) -> tuple[list[DiagnosticCandidate], ClaimGraph]:
    graph = build_claim_graph(steps); ranked = []
    for claim in graph.claims:
        edges = [edge for edge in graph.support if edge.claim_id == claim.claim_id]
        strongest = max((edge.strength for edge in edges), default=0.0)
        unsupported = max(0.0, 1 - strongest / support_threshold)
        later = [location for claim_id, location in graph.reuse if claim_id == claim.claim_id]
        commitment = .75 + (.15 if claim.finalized else 0) + min(.1, len(later) * .04)
        score = unsupported * commitment
        if score <= .05: continue
        supporting = tuple(edge.source_location for edge in sorted(edges, key=lambda edge: -edge.strength)[:3])
        evidence = DiagnosticEvidence("CLAIM001",
            "A consequential claim has weak or missing earlier evidence and may propagate into later steps.",
            claim.text[:500], tuple(dict.fromkeys((*supporting, *later[:3]))))
        ranked.append(DiagnosticCandidate(claim.location, None, min(1.0, score), "claim_evidence_graph", (evidence,)))
        for offset, location in enumerate(later[:2]):
            ranked.append(DiagnosticCandidate(location, None, min(1.0, score * (.9 - offset * .1)), "claim_evidence_graph", (evidence,)))
    unique = {}
    for item in ranked:
        if item.location not in unique or unique[item.location].confidence < item.confidence: unique[item.location] = item
    return sorted(unique.values(), key=lambda item: (-item.confidence, item.location))[:max_candidates], graph
