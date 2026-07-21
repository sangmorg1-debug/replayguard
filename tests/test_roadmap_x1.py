from replayguard.rag import RAGEvaluator
import inspect

from replayguard.semantic import LETTUCE_MODEL, LETTUCE_REVISION, LettuceDetectJudge, SemanticJudgment

from test_phase7 import case, kinds


class FakeJudge:
    def __init__(self, hallucinated=True): self.hallucinated = hallucinated
    def judge(self, contexts, question, answer):
        assert contexts and question and answer
        return SemanticJudgment(self.hallucinated, .91 if self.hallucinated else .02,
                                [{"start": 0, "end": 5, "confidence": .91}] if self.hallucinated else [],
                                "fixture", "revision")


def test_semantic_finding_is_probabilistic_and_non_gating_by_default():
    result = RAGEvaluator(support_threshold=.4, semantic_judge=FakeJudge()).evaluate(case())
    assert result.passed and "semantic_unsupported_claim" in kinds(result)
    finding = next(item for item in result.findings if item.kind == "semantic_unsupported_claim")
    assert finding.severity == "medium" and finding.evidence["probabilistic"] is True
    assert result.metrics["semantic_hallucination_score"] == .91


def test_semantic_gate_requires_explicit_opt_in():
    result = RAGEvaluator(support_threshold=.4, semantic_judge=FakeJudge(), semantic_gate=True).evaluate(case())
    assert not result.passed
    assert next(item for item in result.findings if item.kind == "semantic_unsupported_claim").severity == "high"


def test_supported_semantic_result_has_no_finding():
    result = RAGEvaluator(support_threshold=.4, semantic_judge=FakeJudge(False)).evaluate(case())
    assert result.passed and "semantic_unsupported_claim" not in kinds(result)


def test_default_model_and_revision_are_immutable():
    assert LETTUCE_MODEL == "KRLabsOrg/lettucedect-base-modernbert-en-v1"
    assert len(LETTUCE_REVISION) == 40 and all(character in "0123456789abcdef" for character in LETTUCE_REVISION)
    assert inspect.signature(LettuceDetectJudge).parameters["threshold"].default == .63
