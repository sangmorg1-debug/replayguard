# X1 optional semantic hallucination judge

ReplayGuard now supports a revision-pinned LettuceDetect token-classification judge behind the
optional `semantic` dependency group:

```powershell
pip install -e ".[semantic]"
verify rag evaluate --suite examples/rag-suite.json --semantic
```

The default remains the deterministic lexical evaluator. Semantic findings are probabilistic,
include only offsets/confidence rather than copied claim text, and are medium-severity advisory
findings. They can affect the process exit status only with explicit `--semantic-gate`.

## Reproducibility

- Package: `lettucedetect==0.2.2`
- Model: `KRLabsOrg/lettucedect-base-modernbert-en-v1`
- Model revision: `bbd77832f52f9bd87546a3924c032467921f5c34`
- Model and package license: MIT
- Evaluation data: RAGTruth commit `c103204b9ce28d6bbad859304bf30de72b8ed8fe`
- Benchmark split: good-quality test responses only

`tools/benchmark_ragtruth_semantic.py` is resume-safe and isolates prediction checkpoints by
threshold. It understands RAGTruth's Summary, QA, and Data-to-text source formats rather than
duplicating source text from the stored generation prompt.

## Final RAGTruth measurement

A balanced 300-response calibration slice (50 hallucinated and 50 clean responses from each of
the three task families) produced:

| Metric | Result |
|---|---:|
| Precision | 85.22% |
| Recall | 65.33% |
| F1 | 73.96% |
| Accuracy | 77.00% |

The full run evaluated all 2,675 good-quality test responses. At the raw 0.50 model decision point,
precision was 75.62%, recall 74.02%, F1 74.81%, and accuracy 82.43%.

To select an operating point without tuning on evaluation labels, the benchmark assigns records by
`sha256(response_id) mod 5`: 547 calibration responses select the lowest 0.01 threshold reaching
80% precision (0.63), and the remaining 2,128 records are untouched holdout data.

| Held-out metric at 0.63 | Result |
|---|---:|
| Precision | 80.24% |
| Recall | 70.71% |
| F1 | 75.18% |
| Accuracy | 83.36% |

This clears the roadmap's ≥80% precision and ≥70% recall RAGTruth recommendation gate. The pinned
0.63 threshold is now the product default. The semantic/deterministic union remains rejected: on
the earlier balanced calibration it increased recall to 75.33% but reduced precision to 62.43%.

Cross-domain LLM-AggreFact/FaithBench validation remains open; a RAGTruth-trained model cannot
establish generalization on its training distribution alone. Accordingly, semantic gating is
suitable for opt-in RAGTruth-like English workloads, not a universal factuality guarantee.

LLM-AggreFact is public but access-gated with benchmark-only conditions. After accepting those
conditions, `HF_TOKEN=... python tools/fetch_llm_aggrefact.py` downloads its pinned 29,320-row
test parquet and records byte hashes. Anonymous access was verified to return HTTP 401, so the
project does not bypass or substitute for required acceptance. FaithBench likewise requires an
accessible authorized source before it can become an automated gate.

The adapter includes a text-only compatibility guard for environments where an unrelated,
binary-incompatible `torchvision` installation would otherwise prevent Transformers from loading
ModernBERT. It does not uninstall or modify the vision package.
