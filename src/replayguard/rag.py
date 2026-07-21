from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .semantic import SemanticJudge

TOKEN = re.compile(r"[a-z0-9]+", re.I)
CITATION = re.compile(r"\[([^\[\]]+)\]")
INJECTION = re.compile(
    r"(?i)(ignore (?:all |any )?(?:previous|prior|system|developer) instructions|"
    r"system prompt|do not trust (?:the )?(?:user|above)|exfiltrat|reveal (?:the )?(?:secret|password|token)|"
    r"act as (?:an? )?(?:admin|system)|<\s*(?:system|assistant)\b|tool[_ -]?call)"
)
NEGATION = {"not", "no", "never", "neither", "without", "fails", "failed", "false"}


def _tokens(text: str) -> set[str]:
    return {item.lower() for item in TOKEN.findall(text) if len(item) > 2}


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _overlap(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / len(a) if a else 1.0


@dataclass(slots=True)
class RAGDocument:
    id: str
    text: str
    title: str = ""
    source_uri: str = ""
    version: str = "unversioned"
    updated_at: str | None = None
    authority: float = 0.5
    tenant_id: str = "default"
    allowed_principals: list[str] = field(default_factory=list)
    license: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def digest(self) -> str: return _sha(asdict(self))


@dataclass(slots=True)
class RetrievedChunk:
    id: str
    document_id: str
    text: str
    score: float
    rank: int
    tenant_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RAGCase:
    id: str
    query: str
    answer: str
    documents: list[RAGDocument]
    retrieved: list[RetrievedChunk]
    expected_document_ids: list[str] = field(default_factory=list)
    expected_answerable: bool = True
    tenant_id: str = "default"
    principal_id: str = "anonymous"
    citations: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RAGCase":
        data = dict(value)
        data["documents"] = [RAGDocument(**item) for item in data.get("documents", [])]
        data["retrieved"] = [RetrievedChunk(**item) for item in data.get("retrieved", [])]
        return cls(**data)


@dataclass(slots=True)
class Finding:
    kind: str
    severity: str
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RAGResult:
    case_id: str
    passed: bool
    metrics: dict[str, float]
    findings: list[Finding]
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]: return asdict(self)


class RAGEvaluator:
    def __init__(self, *, freshness_days: int = 365, relevance_threshold: float = .15,
                 support_threshold: float = .55, authority_threshold: float = .5,
                 semantic_judge: SemanticJudge | None = None, semantic_gate: bool = False) -> None:
        self.freshness_days = freshness_days
        self.relevance_threshold = relevance_threshold
        self.support_threshold = support_threshold
        self.authority_threshold = authority_threshold
        self.semantic_judge = semantic_judge
        self.semantic_gate = semantic_gate

    def evaluate(self, case: RAGCase, context: dict[str, Any] | None = None) -> RAGResult:
        context = context or {}
        docs = {item.id: item for item in case.documents}
        findings: list[Finding] = []
        retrieved_ids = [item.document_id for item in case.retrieved]
        expected = set(case.expected_document_ids)
        recall = len(expected & set(retrieved_ids)) / len(expected) if expected else 1.0
        precision = len(expected & set(retrieved_ids)) / len(retrieved_ids) if retrieved_ids and expected else (1.0 if not expected else 0.0)
        relevance = sum(_overlap(case.query, item.text) for item in case.retrieved) / max(len(case.retrieved), 1)
        if expected and recall < 1: findings.append(Finding("missing_coverage", "high", "Expected supporting documents were not retrieved.", {"missing": sorted(expected - set(retrieved_ids))}))
        if case.retrieved and relevance < self.relevance_threshold: findings.append(Finding("low_relevance", "medium", "Retrieved chunks have low lexical relevance to the query.", {"score": relevance}))

        now = datetime.now(timezone.utc)
        for chunk in case.retrieved:
            doc = docs.get(chunk.document_id)
            if not doc:
                findings.append(Finding("missing_source", "high", "Retrieved chunk has no source document.", {"chunk": chunk.id, "document": chunk.document_id})); continue
            if chunk.tenant_id != case.tenant_id or doc.tenant_id != case.tenant_id:
                findings.append(Finding("cross_tenant_retrieval", "critical", "A retrieved source belongs to another tenant.", {"document": doc.id}))
            if doc.allowed_principals and case.principal_id not in doc.allowed_principals:
                findings.append(Finding("permission_violation", "critical", "Principal is not permitted to retrieve this source.", {"document": doc.id}))
            if doc.authority < self.authority_threshold:
                findings.append(Finding("low_authority", "medium", "A retrieved source is below the authority threshold.", {"document": doc.id, "authority": doc.authority}))
            if doc.updated_at:
                try:
                    age = (now - datetime.fromisoformat(doc.updated_at.replace("Z", "+00:00"))).days
                    if age > self.freshness_days: findings.append(Finding("stale_source", "medium", "A retrieved source exceeds the freshness limit.", {"document": doc.id, "age_days": age}))
                except ValueError: findings.append(Finding("invalid_freshness", "low", "Source updated_at is not ISO-8601.", {"document": doc.id}))
            if INJECTION.search(chunk.text): findings.append(Finding("document_prompt_injection", "high", "Retrieved content contains instruction-like attack text.", {"chunk": chunk.id}))

        cited = case.citations or CITATION.findall(case.answer)
        chunk_map = {item.id: item for item in case.retrieved}
        invalid = sorted(set(cited) - set(chunk_map))
        if invalid: findings.append(Finding("invalid_citation", "high", "Answer cites chunks that were not retrieved.", {"citations": invalid}))
        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", case.answer) if len(_tokens(item)) >= 2]
        unsupported: list[str] = []
        for sentence in sentences:
            refs = CITATION.findall(sentence) or cited
            evidence = " ".join(chunk_map[item].text for item in refs if item in chunk_map)
            clean = CITATION.sub("", sentence)
            if not evidence or _overlap(clean, evidence) < self.support_threshold: unsupported.append(clean)
        support = 1 - len(unsupported) / max(len(sentences), 1)
        if unsupported and case.expected_answerable:
            findings.append(Finding("unsupported_claim", "high", "One or more answer claims are not supported by cited retrieved text.", {"claims": unsupported}))
        if not case.expected_answerable and sentences and support >= self.support_threshold:
            findings.append(Finding("answered_unanswerable", "high", "The case is marked unanswerable but received a substantive answer."))

        metrics = {"retrieval_recall": recall, "retrieval_precision": precision, "retrieval_relevance": relevance,
                   "citation_support": support, "mean_authority": sum((docs[c.document_id].authority for c in case.retrieved if c.document_id in docs), 0.0) / max(len(case.retrieved), 1)}
        if self.semantic_judge and case.expected_answerable:
            judgment = self.semantic_judge.judge([item.text for item in case.retrieved], case.query, case.answer)
            metrics["semantic_hallucination_score"] = judgment.score
            if judgment.hallucinated:
                findings.append(Finding("semantic_unsupported_claim", "high" if self.semantic_gate else "medium",
                                        "The optional semantic judge identified unsupported answer spans.",
                                        {"spans": judgment.spans, "model": judgment.model, "revision": judgment.revision,
                                         "probabilistic": True, "gating": self.semantic_gate}))

        contradictions = self._contradictions(case.retrieved)
        if contradictions: findings.append(Finding("contradictory_sources", "medium", "Retrieved sources contain potentially contradictory statements.", {"pairs": contradictions}))
        provenance = build_provenance(case, context)
        return RAGResult(case.id, not any(item.severity in {"high", "critical"} for item in findings), metrics, findings, provenance)

    @staticmethod
    def _contradictions(chunks: list[RetrievedChunk]) -> list[list[str]]:
        found = []
        for index, left in enumerate(chunks):
            for right in chunks[index + 1:]:
                common = _tokens(left.text) & _tokens(right.text)
                left_neg, right_neg = bool(_tokens(left.text) & NEGATION), bool(_tokens(right.text) & NEGATION)
                if len(common) >= 4 and left_neg != right_neg: found.append([left.id, right.id])
        return found


def build_provenance(case: RAGCase, context: dict[str, Any]) -> dict[str, Any]:
    answer_id = f"answer:{case.id}"
    nodes = [{"id": answer_id, "type": "answer", "sha256": _sha(case.answer)},
             {"id": f"response:{case.id}", "type": "model_response", "model": context.get("model", "unknown")},
             {"id": f"prompt:{case.id}", "type": "prompt", "sha256": _sha(context.get("prompt", case.query))},
             {"id": f"index:{context.get('index_version', 'unknown')}", "type": "index", "version": context.get("index_version", "unknown")},
             {"id": f"embedding:{context.get('embedding_model', 'unknown')}", "type": "embedding_model"},
             {"id": f"pipeline:{context.get('ingestion_pipeline', 'unknown')}", "type": "ingestion_pipeline"}]
    edges = [(answer_id, f"response:{case.id}"), (f"response:{case.id}", f"prompt:{case.id}"),
             (f"prompt:{case.id}", f"index:{context.get('index_version', 'unknown')}"),
             (f"index:{context.get('index_version', 'unknown')}", f"embedding:{context.get('embedding_model', 'unknown')}"),
             (f"index:{context.get('index_version', 'unknown')}", f"pipeline:{context.get('ingestion_pipeline', 'unknown')}")]
    docs = {item.id: item for item in case.documents}
    for chunk in case.retrieved:
        nodes.append({"id": f"chunk:{chunk.id}", "type": "retrieved_chunk", "sha256": _sha(chunk.text), "rank": chunk.rank})
        edges.append((f"response:{case.id}", f"chunk:{chunk.id}"))
        doc = docs.get(chunk.document_id)
        if doc:
            node_id = f"document:{doc.id}@{doc.version}"
            if not any(item["id"] == node_id for item in nodes): nodes.append({"id": node_id, "type": "source_document", "sha256": doc.digest, "origin": doc.source_uri, "version": doc.version})
            edges.append((f"chunk:{chunk.id}", node_id)); edges.append((node_id, f"pipeline:{context.get('ingestion_pipeline', 'unknown')}"))
    return {"version": "1.0", "id": uuid4().hex, "nodes": nodes, "edges": [{"from": a, "to": b} for a, b in edges], "sha256": _sha([nodes, edges])}


def evaluate_file(path: str | Path, *, semantic_judge: SemanticJudge | None = None,
                  semantic_gate: bool = False) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    evaluator = RAGEvaluator(**value.get("thresholds", {}), semantic_judge=semantic_judge, semantic_gate=semantic_gate)
    results = [evaluator.evaluate(RAGCase.from_dict(item), value.get("context", {})) for item in value.get("cases", [])]
    return {"schema_version": "1.0", "suite": value.get("name", Path(path).stem), "results": [item.to_dict() for item in results],
            "summary": {"total": len(results), "passed": sum(item.passed for item in results), "failed": sum(not item.passed for item in results)}}


def compare_rag(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    a, b = {item["case_id"]: item for item in left["results"]}, {item["case_id"]: item for item in right["results"]}
    changed = []
    for case_id in sorted(a.keys() | b.keys()):
        old, new = a.get(case_id), b.get(case_id)
        if old != new:
            changed.append({"case_id": case_id, "status": "added" if old is None else "removed" if new is None else "changed",
                            "pass_changed": bool(old and new and old["passed"] != new["passed"]),
                            "provenance_changed": bool(old and new and old["provenance"]["sha256"] != new["provenance"]["sha256"])})
    return {"left_suite": left.get("suite"), "right_suite": right.get("suite"), "changed": changed,
            "regressions": sum(item["pass_changed"] and not b[item["case_id"]]["passed"] for item in changed if item["case_id"] in b)}
