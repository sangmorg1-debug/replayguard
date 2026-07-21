# Phase 7 RAG reliability and provenance completion record

Phase 7 engineering is complete. Customer adoption and production prevention gates remain external validation work and are not represented as code achievements.

## Implemented

- Deterministic evaluation of retrieval relevance, expected-document recall and precision, missing coverage, source freshness, source authority, answerability, citation validity, and claim support.
- Fail-closed findings for cross-tenant retrieval and principal permission violations.
- Detection of instruction-like payloads in retrieved documents without executing or rendering them.
- Potential source-contradiction detection, chunking/index provenance hashes, and comparison of two RAG releases.
- A provenance graph connecting answer, response, prompt, retrieved chunks, versioned source documents, index, embedding model, and ingestion pipeline.
- A schema-valid AIBOM inventory for applications, models and aliases, prompts, agents, tools/MCP dependencies, evaluation suites, retrieval collections, embedding models, data sources, packages, licenses, hashes, dependencies, and generation context.
- Local-only reports: document bodies need not be uploaded to the hosted service.

## Real public evaluation data

`tools/fetch_ragtruth.py` downloads RAGTruth at commit `c103204b9ce28d6bbad859304bf30de72b8ed8fe` and deterministically selects 50 manually labeled hallucinated and 50 manually labeled clean test responses. The source text, response, model, task, and word-level annotations are retained in `tests/data/ragtruth-sample.json`. RAGTruth is MIT licensed.

The detector is deliberately a deterministic lexical evidence check, not an unversioned model judge. On the pinned balanced slice it reaches 90% precision (9 true positives and 1 false positive) at the documented 0.45 threshold. Recall is only 18%; this is a high-confidence CI gate, not a comprehensive semantic entailment detector. Probabilistic NLI or model judges should be reported separately if added later.

The controlled document-poisoning benchmark seeds instruction payloads into retrieved content. It detects 100/100 attacks, flags 100/100 cross-tenant retrievals, and produces no tool or network side effects.

Reproduce:

```powershell
python tools/fetch_ragtruth.py
python tools/benchmark_rag.py
python -m pytest tests/test_phase7.py -q
verify rag evaluate --suite examples/rag-suite.json --output .verify/rag-report.json
verify rag aibom --manifest examples/aibom-manifest.json --output .verify/aibom.json
```

## Security and integrity boundaries

- Retrieved documents are inert data; evaluation never executes document instructions.
- Tenant and permission checks operate independently of authentication.
- Content remains local unless a caller explicitly uploads it through another component.
- Source, chunk, prompt, answer, and complete graph hashes make silent provenance changes visible.
- Missing source records and invalid citations fail with high-severity findings.
- The prompt-injection detector is a defensive pattern layer, not proof that arbitrary adversarial language is safe.

## Gate status

Engineering gates achieved:

- Unsupported-claim precision is 90% on the pinned controlled RAGTruth slice.
- The controlled tenant benchmark identifies every cross-tenant retrieval.
- Every evaluated answer maps to exact document, index, embedding, and ingestion versions in its provenance graph.
- The seeded document-poisoning benchmark detects 100/100 attacks.
- Release comparison identifies changed results and provenance.
- AIBOM output validates against `schemas/aibom-v1.schema.json`.
- Reports are generated locally without hosted document contents.

External gates still requiring real adopters:

- Five teams running RAG checks in CI.
- Three teams preventing a known retrieval regression.
- Two customers naming provenance as a purchasing requirement.

## Standards and data basis

- RAGTruth is the real, manually annotated hallucination corpus used by the automated benchmark.
- BEIR/SciFact defines the corpus/query/qrels pattern supported by the retrieval metrics and is the recommended next external retrieval corpus.
- CycloneDX AI/ML BOM concepts informed the inventory categories. ReplayGuard declares and validates its own `ReplayGuard-AIBOM` schema; it does not mislabel the current export as a CycloneDX document.
