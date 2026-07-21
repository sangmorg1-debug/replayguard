"""Error-first hypothesis generation and evidence verification for candidate recall."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from .claim_graph import COMMIT, EVIDENCE, EXPLORATORY, similarity, terms
from .diagnostic_candidates import DiagnosticCandidate, DiagnosticEvidence

ERROR = re.compile(r"(?i)\b(error|exception|failed|failure|invalid|timeout|not found|forbidden|unauthorized|incorrect|wrong)\b")
ABORT = re.compile(r"(?i)\b(cannot|unable|give up|no answer|replan counter exceeded|terminating)\b")
NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")


@dataclass(frozen=True, slots=True)
class FailureHypothesis:
    hypothesis_id: str
    error_type: str
    symptom_location: str
    candidate_location: str
    rationale: str


@dataclass(frozen=True, slots=True)
class HypothesisVerification:
    hypothesis_id: str
    verdict: str  # entail / neutral / contradict
    confidence: float
    evidence_locations: tuple[str, ...]


def verify_hypotheses(steps: Sequence[tuple[str, str]], *, max_candidates: int = 8
                      ) -> tuple[list[DiagnosticCandidate], list[FailureHypothesis], list[HypothesisVerification]]:
    if not steps: return [], [], []
    token_sets = [terms(text) for _, text in steps]; frequencies = Counter(word for row in token_sets for word in row)
    symptom_indices = []
    for index, (_, text) in enumerate(steps):
        if ERROR.search(text) or ABORT.search(text) or COMMIT.search(text): symptom_indices.append(index)
    symptom_indices.append(len(steps) - 1)
    symptom_indices = list(dict.fromkeys(symptom_indices))
    hypotheses = []; verifications = []
    for symptom_index in symptom_indices:
        symptom_location, symptom_text = steps[symptom_index]
        error_type = "explicit_failure" if ERROR.search(symptom_text) else "premature_abort" if ABORT.search(symptom_text) else "unsupported_commitment"
        ranked_earlier = sorted(range(symptom_index),
            key=lambda index: (similarity(token_sets[symptom_index], token_sets[index], frequencies), index), reverse=True)
        candidates = [symptom_index, *ranked_earlier[:3]]
        for candidate_index in candidates:
            candidate_location, candidate_text = steps[candidate_index]
            overlap = similarity(token_sets[symptom_index], token_sets[candidate_index], frequencies)
            direct = candidate_index == symptom_index
            evidence_like = bool(EVIDENCE.search(candidate_text)) and not bool(ERROR.search(candidate_text))
            exploratory = bool(EXPLORATORY.search(candidate_text.strip()))
            conflicting_numbers = bool(set(NUMBER.findall(candidate_text)) and set(NUMBER.findall(symptom_text))
                                       and set(NUMBER.findall(candidate_text)).isdisjoint(NUMBER.findall(symptom_text)))
            if direct:
                confidence = .92 if ERROR.search(symptom_text) else .82 if ABORT.search(symptom_text) else .72
                verdict = "entail"
            elif evidence_like and conflicting_numbers:
                confidence = .85; verdict = "contradict"
            elif overlap >= .16 and not exploratory:
                confidence = min(.9, .55 + overlap); verdict = "entail"
            elif evidence_like and overlap >= .1:
                confidence = .25; verdict = "contradict"
            else:
                confidence = min(.49, .2 + overlap); verdict = "neutral"
            hypothesis = FailureHypothesis(f"h{len(hypotheses) + 1}", error_type, symptom_location, candidate_location,
                "Verify whether this location introduced or committed the failure visible at the symptom location.")
            hypotheses.append(hypothesis); verifications.append(HypothesisVerification(hypothesis.hypothesis_id, verdict,
                confidence, tuple(dict.fromkeys((candidate_location, symptom_location)))))
    best = {}
    for hypothesis, verification in zip(hypotheses, verifications):
        if verification.verdict == "contradict": continue
        score = verification.confidence * (1.0 if verification.verdict == "entail" else .55)
        evidence = DiagnosticEvidence("HYP001",
            f"{verification.verdict.title()} verification of an {hypothesis.error_type} hypothesis.",
            hypothesis.rationale, verification.evidence_locations)
        item = DiagnosticCandidate(hypothesis.candidate_location, None, score, "hypothesis_verifier", (evidence,))
        if item.location not in best or best[item.location].confidence < item.confidence: best[item.location] = item
    ranked = sorted(best.values(), key=lambda item: (-item.confidence, item.location))[:max_candidates]
    return ranked, hypotheses, verifications
