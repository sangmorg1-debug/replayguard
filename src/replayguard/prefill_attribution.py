"""Two-pass, prefill-only failure attribution following the MASPrism paper specification.

This is an independent paper-spec reproduction. The authors' v1.0.0 artifact was restricted and
its linked GitHub repository unavailable when this module was implemented (2026-07-20).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol, Sequence

from .diagnostic_candidates import DiagnosticCandidate, DiagnosticEvidence

FILTER_PROMPT = ("This trace has been truncated. Each step shows a bounded prefix of key content. "
                 "[...] marks omitted text. Focus on error patterns and causal chains. Omissions are expected.\n")
DIAGNOSIS_PROMPT = ("This execution trace has been reconstructed. Key steps retain full content; other steps are "
                    "compressed with [...] placeholders. Analyze which earlier step or location is most responsible "
                    "for the observed failure.\n")
SYMPTOM_NOTE = "[Note]: The next step shows anomalous behavior. Trace backward to identify which earlier step caused it.\n"
FAILURE_MARKER = re.compile(r"(?i)\b(error|exception|failed|failure|invalid|timeout|not found|forbidden|unauthorized)\b")


@dataclass(frozen=True, slots=True)
class PrefillSignals:
    nll: tuple[float, ...]
    attention: tuple[tuple[float, ...], ...]  # query step -> earlier/key step
    input_tokens: int


class PrefillBackend(Protocol):
    model_id: str
    revision: str
    def signals(self, prefix: str, steps: Sequence[tuple[str, str]]) -> PrefillSignals: ...


class QwenPrefillBackend:
    """Hugging Face eager-attention backend; performs no decoding."""
    model_id = "Qwen/Qwen3-0.6B"

    def __init__(self, *, revision: str = "c1899de289a04d12100db370d81485cdf75e47ca",
                 device: str | None = None, max_tokens: int = 1024):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.revision = revision; self.max_tokens = max_tokens
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, revision=revision)
        self.model = AutoModelForCausalLM.from_pretrained(self.model_id, revision=revision,
            torch_dtype=dtype, attn_implementation="eager").to(self.device).eval()

    def signals(self, prefix: str, steps: Sequence[tuple[str, str]]) -> PrefillSignals:
        import torch
        pieces = [prefix] + [f"\n[Step {location}]\n{text}" for location, text in steps]
        encoded = [self.tokenizer(piece, add_special_tokens=index == 0).input_ids for index, piece in enumerate(pieces)]
        total = sum(map(len, encoded))
        if total > self.max_tokens:
            raise ValueError(f"prefill prompt has {total} tokens, above configured limit {self.max_tokens}")
        ids = [token for piece in encoded for token in piece]; ranges = []; cursor = len(encoded[0])
        for piece in encoded[1:]: ranges.append((cursor, cursor + len(piece))); cursor += len(piece)
        input_ids = torch.tensor([ids], device=self.device)
        with torch.inference_mode():
            output = self.model(input_ids=input_ids, output_attentions=True, use_cache=False, return_dict=True)
        log_probs = torch.log_softmax(output.logits[0, :-1].float(), dim=-1)
        token_nll = -log_probs.gather(1, input_ids[0, 1:].unsqueeze(1)).squeeze(1)
        nll = []
        for start, end in ranges:
            left, right = max(0, start - 1), max(0, end - 1)
            nll.append(float(token_nll[left:right].mean().item()) if right > left else 0.0)
        layers = output.attentions; selected = layers[max(0, math.floor(len(layers) * .8)):]
        averaged = torch.stack([layer[0].float().mean(dim=0) for layer in selected]).mean(dim=0)
        matrix = []
        for query_start, query_end in ranges:
            row = []
            for key_start, key_end in ranges:
                if key_start >= query_start: row.append(0.0)
                else: row.append(float(averaged[query_start:query_end, key_start:key_end].sum(dim=1).mean().item()))
            matrix.append(tuple(row))
        del output, averaged
        if self.device == "cuda": torch.cuda.empty_cache()
        return PrefillSignals(tuple(nll), tuple(matrix), len(ids))


def _truncate(text: str, budget: int) -> str:
    return text if len(text) <= budget else text[:budget] + " [...]"


def attribute(steps: Sequence[tuple[str, str]], backend: PrefillBackend, *, symptom_ratio: float = .5,
              candidate_k: int = 5, consensus_weight: float = .3, max_candidates: int = 3,
              prefix_chars: int = 120, focus_chars: int = 480) -> tuple[list[DiagnosticCandidate], dict]:
    if not steps: return [], {"prefill_passes": 0, "input_tokens": 0}
    compact = [(location, _truncate(text, prefix_chars)) for location, text in steps]
    first = backend.signals(FILTER_PROMPT, compact)
    symptom_count = max(1, round(len(steps) * symptom_ratio))
    symptom_rank = sorted(range(len(steps)), key=lambda i: (bool(FAILURE_MARKER.search(steps[i][1])), first.nll[i]), reverse=True)
    symptoms = symptom_rank[:symptom_count]
    routing = {candidate: sum(first.attention[symptom][candidate] for symptom in symptoms if candidate < symptom)
               for candidate in range(len(steps))}
    candidates = sorted(routing, key=lambda i: (routing[i], -i), reverse=True)[:candidate_k]
    earliest = min(symptoms); restored = []
    for index, (location, text) in enumerate(steps):
        value = _truncate(text, focus_chars) if index in set(symptoms + candidates) else _truncate(text, prefix_chars)
        if index == earliest: value = SYMPTOM_NOTE + value
        restored.append((location, value))
    second = backend.signals(DIAGNOSIS_PROMPT, restored)
    updated = sorted(range(len(steps)), key=lambda i: (bool(FAILURE_MARKER.search(steps[i][1])), second.nll[i]), reverse=True)[:symptom_count]
    scores = {}; links = {}
    for candidate in candidates:
        individual = []
        for symptom in updated:
            if candidate >= symptom: continue
            earlier = second.attention[symptom][:symptom]
            mean_attention = sum(earlier) / len(earlier) if earlier else 0.0
            normalized = second.attention[symptom][candidate] / mean_attention if mean_attention > 0 else 0.0
            contrast = 1 + max(0.0, second.nll[symptom] - second.nll[candidate])
            individual.append((normalized * contrast, symptom))
        base = sum(score for score, _ in individual)
        top_five_count = sum(candidate in sorted(range(symptom), key=lambda i: second.attention[symptom][i], reverse=True)[:5]
                             for symptom in updated if symptom > 0)
        scores[candidate] = base * (1 + consensus_weight * top_five_count)
        links[candidate] = [symptom for score, symptom in individual if score > 0]
    ranked = sorted(candidates, key=lambda i: (scores[i], -i), reverse=True)[:max_candidates]
    scale = max((scores[i] for i in ranked), default=0.0)
    result = [DiagnosticCandidate(steps[i][0], None, scores[i] / scale if scale else 0.0, "qwen_prefill",
        (DiagnosticEvidence("PREFILL001", "Two-pass NLL/attention routing selected this earlier failure-source candidate.",
            steps[i][1][:500], tuple(steps[j][0] for j in links[i])),)) for i in ranked]
    return result, {"prefill_passes": 2, "input_tokens": first.input_tokens + second.input_tokens,
                    "symptoms": [steps[i][0] for i in updated], "model": backend.model_id,
                    "revision": backend.revision, "decoded_tokens": 0}
