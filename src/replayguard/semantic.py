"""Optional probabilistic grounding judges; never imported by deterministic-only users."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

LETTUCE_MODEL = "KRLabsOrg/lettucedect-base-modernbert-en-v1"
LETTUCE_REVISION = "bbd77832f52f9bd87546a3924c032467921f5c34"


@dataclass(slots=True)
class SemanticJudgment:
    hallucinated: bool
    score: float
    spans: list[dict[str, Any]]
    model: str
    revision: str

    def to_dict(self) -> dict[str, Any]: return asdict(self)


class SemanticJudge(Protocol):
    def judge(self, contexts: list[str], question: str | None, answer: str) -> SemanticJudgment: ...


class LettuceDetectJudge:
    """Lazy, revision-pinned LettuceDetect token-classification adapter."""

    def __init__(self, *, model: str = LETTUCE_MODEL, revision: str = LETTUCE_REVISION,
                 threshold: float = .63, device: str = "cpu", max_length: int = 4096) -> None:
        if not 0 <= threshold <= 1: raise ValueError("semantic threshold must be between 0 and 1")
        self.model_id, self.revision, self.threshold = model, revision, threshold
        try:
            from huggingface_hub import snapshot_download
            # Transformers treats an installed torchvision as available even when its binary
            # operators are incompatible with torch. This text-only model does not use vision.
            try:
                import torchvision  # noqa: F401
            except (ImportError, RuntimeError):
                import transformers.utils as transformer_utils
                import transformers.utils.import_utils as import_utils
                import_utils.is_torchvision_available = lambda: False
                transformer_utils.is_torchvision_available = lambda: False
            from lettucedetect.models.inference import HallucinationDetector
            from lettucedetect.datasets.hallucination_dataset import HallucinationDataset
            from lettucedetect.detectors.prompt_utils import PromptUtils
            import torch
        except ImportError as exc:
            raise RuntimeError('semantic evaluation requires `pip install "replayguard[semantic]"`') from exc
        local = snapshot_download(model, revision=revision,
                                  allow_patterns=["*.json", "*.safetensors", "*.txt", "tokenizer.*"])
        self.detector = HallucinationDetector(method="transformer", model_path=local,
                                              device=device, max_length=max_length)
        self._dataset, self._prompts, self._torch = HallucinationDataset, PromptUtils, torch

    def judge(self, contexts: list[str], question: str | None, answer: str) -> SemanticJudgment:
        spans = self.detector.predict(context=contexts, question=question, answer=answer,
                                      output_format="spans", min_confidence=self.threshold)
        safe = [{"start": int(item["start"]), "end": int(item["end"]),
                 "confidence": float(item.get("confidence", 0))} for item in spans]
        score = max((item["confidence"] for item in safe), default=0.0)
        return SemanticJudgment(bool(safe), score, safe, self.model_id, self.revision)

    def judge_many(self, cases: list[tuple[list[str], str | None, str]], *, batch_size: int = 8) -> list[SemanticJudgment]:
        """Batch the same token-classification logic used by ``judge`` for CPU benchmarks."""
        if batch_size < 1: raise ValueError("batch_size must be positive")
        results: list[SemanticJudgment] = []; engine = self.detector.detector
        for start in range(0, len(cases), batch_size):
            batch = cases[start:start + batch_size]; prepared = []
            for contexts, question, answer in batch:
                prompt = self._prompts.format_context(contexts, question, "en")
                encoding, _, offsets, answer_start = self._dataset.prepare_tokenized_input(
                    engine.tokenizer, prompt, answer, engine.max_length)
                prepared.append((encoding, offsets, answer_start, answer))
            padded = engine.tokenizer.pad(
                [{"input_ids": item[0].input_ids[0], "attention_mask": item[0].attention_mask[0]} for item in prepared],
                padding=True, return_tensors="pt")
            inputs = {key: value.to(engine.device) for key, value in padded.items() if key in {"input_ids", "attention_mask"}}
            with self._torch.no_grad():
                probabilities = self._torch.softmax(engine.model(**inputs).logits, dim=-1)
                predictions = self._torch.argmax(probabilities, dim=-1)
            for row, (_, offsets, answer_start, answer) in enumerate(prepared):
                spans = []; current = None; answer_offset = offsets[answer_start][0].item() if answer_start < offsets.size(0) else 0
                usable = min(offsets.size(0), int(inputs["attention_mask"][row].sum().item()))
                for token in range(answer_start, usable):
                    left, right = offsets[token].tolist()
                    if left == right: continue
                    confidence = float(probabilities[row, token, 1].item())
                    hallucinated = predictions[row, token].item() == 1 and confidence >= self.threshold
                    relative = (left - answer_offset, right - answer_offset)
                    if hallucinated:
                        if current is None: current = {"start": relative[0], "end": relative[1], "confidence": confidence}
                        else: current["end"] = relative[1]; current["confidence"] = max(current["confidence"], confidence)
                    elif current is not None:
                        spans.append(current); current = None
                if current is not None: spans.append(current)
                score = max((item["confidence"] for item in spans), default=0.0)
                results.append(SemanticJudgment(bool(spans), score, spans, self.model_id, self.revision))
        return results
