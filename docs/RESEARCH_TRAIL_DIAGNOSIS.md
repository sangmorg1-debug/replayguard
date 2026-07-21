# TRAIL failure-diagnosis research: consolidated report

This report merges `TRAIL_TINY_MODEL_EXPERIMENT.md` and `STACKED_DIAGNOSTICS_EXPERIMENT.md` into one
place: what was tried, what the numbers actually are, what generalizes, and what ships. It exists
because the two source documents grew into nine stacked experiment layers plus a separate model
experiment, and no single document previously stated the bottom line. Nothing here was re-run to
produce this report — every number is quoted from the existing pinned `.verify/reports/*.json`
artifacts and the two source documents, which remain in place with a pointer to this report.

## Motivation

ReplayGuard's core thesis is "replay and diagnose agent failures." Patronus AI's TRAIL dataset (148
real annotated agent-execution traces, MIT-licensed, access-gated on Hugging Face) makes that thesis
measurable: state-of-the-art LLMs localize only ~11% of TRAIL's human-labeled errors on the paper's
own metric. The research question was whether structured decomposition (deterministic rules, a
tiny local model, a claim/evidence graph, hypothesis verification, calibrated ranking) plus cheap
local inference could do better than monolithic frontier-model prompting — and, separately, whether
any result generalizes beyond the 148 traces it was measured on.

## Datasets, provenance, and redistribution status

| Dataset | Revision | License | Access | Redistribution |
|---|---|---|---|---|
| `PatronusAI/TRAIL` | `b424ce63d5973d5dcd7169b1bc3c07ccdee276d1` | MIT | Gated (HF access conditions accepted) | Never — private `.verify/` cache only |
| `patronus-ai/trail-benchmark` (public mirror) | `0ffbed9db859b4a66250dc783fa4dccf86869595` | MIT | Public | Public data, still cached under ignored `.verify/` |
| `NJU-LINK/TELBench` | `307d870d7424be265653bb7a566793cc217105be` | Apache-2.0 | Public (encrypted release, public passphrase) | Not redistributed by ReplayGuard |
| `microsoft/AgentRx` | `f228165bfec60a801fd5fedd9d8ffe0f9de0c69d` | MIT | Public | Not redistributed by ReplayGuard |
| RootSE | `c3e54cf25f99eddd85d8c9cbe3f41528e5e7f957` | MIT | Public | Not redistributed by ReplayGuard |
| RAGTruth (for X1 context) | `c103204b9ce28d6bbad859304bf30de72b8ed8fe` | MIT | Public | Not redistributed by ReplayGuard |

TRAIL is the only gated dataset in this report. It is never committed to the repository or any
public location; it lives exclusively in the ignored `.verify/` cache, verified by pinned revision
and SHA-256 on every fetch. This constraint is non-negotiable and applies to anything derived from
raw TRAIL content (predictions, traces, or annotation excerpts) as much as to the raw files.

## Methodology and integrity controls

- **Trace-grouped folds.** Every cross-validation split assigns whole traces to folds by SHA-256 of
  trace ID; no spans from one trace cross a fold boundary, preventing leakage through shared context.
- **Leave-one-dataset-out (LODO).** The stronger generalization gate trains on two of
  {TRAIL, TELBench, AgentRx} and evaluates on the third, with zero examples from the held-out corpus.
- **Annotation stripping.** `Event.attributes`, preserved raw spans, and `trail.annotations` are
  never fed to any model or feature extractor — those fields carry gated annotation metadata.
- **Unchanged official scorer.** TRAIL predictions are scored with the pinned upstream scorer
  (SHA-256 `ed81ebd…`) run unmodified; ReplayGuard does not implement its own competing metric for
  the headline number.
- **Spent-holdout discipline.** Once a partition is used to select a policy (the Layer 7 62/86
  calibration/holdout split; the RootSE external set), it is documented as spent and never reused as
  if it were a fresh untouched gate.
- **Paired bootstrap.** Comparative claims (meta-ranker vs. claim graph) use trace-paired bootstrap
  resampling and report confidence intervals, not just point estimates.

## Results

### N2 deterministic baseline (`.verify/reports/trail-n2.json`, `trail-n2-hardened.json`)

| Layer / experiment | Real result | Verdict |
|---|---|---|
| N2 deterministic baseline (TRAIL, all 148 traces) | 17.84% macro-joint accuracy / 10.24% pair precision / 10.55% pair F1; exec-API subset 2.99% | Recall-like metric — must publish with precision/F1, never alone |
| N2 hardened 3-candidate (127-trace untouched holdout) | 17.75% precision / 8.29% recall / 11.30% F1 | Less noisy, still far below an automated-gate bar |

### Tiny local model (`.verify/reports/trail-tiny-experiment/`)

| System | Macro joint | Pair precision | Pair F1 |
|---|---:|---:|---:|
| Frozen deterministic, top 3 | 14.94% | 17.90% | 11.41% |
| Tiny TF-IDF model, 5-fold out-of-fold, top 3 | 14.91% | 29.95% | 20.78% |
| Exploratory deterministic+model hybrid, top 3 | 19.40% | 29.95% | 20.78% |

Beats the TRAIL paper's ~11% combined Gemini 2.5 Pro Preview figure, which is real evidence that
trace decomposition plus cheap local inference can outperform monolithic long-context prompting. It
is **not** a state-of-the-art claim: Holistic Evaluation reports 61–64% and Pisama claims 59.9% (see
Competitive landscape below).

### Cross-domain transfer (tiny model)

| Train → test | Macro joint | Precision | F1 |
|---|---:|---:|---:|
| GAIA → SWE-Bench | 6.04% | 17.20% | 9.20% |
| SWE-Bench → GAIA | 0.97% | 1.99% | 1.50% |

The cross-validation gain contains substantial within-domain learning and **does not generalize**
across GAIA/SWE-Bench. This result blocks any claim that the tiny model learned transferable
structure rather than memorizing TRAIL-specific surface patterns.

### Stacked diagnostics layers (`.verify/reports/stacked-invariants.json`, `claim-graph.json`,
`meta-ranker.json`, `meta-ranker-hypotheses.json`, `category-assignment.json`,
`trail-safe-router.json`, `nested-router.json`, `rootse-external.json`)

| Layer | TRAIL (location F1 unless noted) | TELBench | AgentRx | Verdict |
|---|---:|---:|---:|---|
| L1 deterministic invariants (conservative hybrid) | 11.12% (no gain over 11.41% baseline) | 20.50% | 4.49% | Useful complementary signal outside TRAIL only |
| L2 Qwen3-0.6B prefill attribution (MASPrism-style, pilot) | 0.00% (32 cases) | 41.51% | 1.52% | **Not accepted as a MASPrism reproduction** — official artifact restricted/unavailable, zero TRAIL matches contradicts the paper |
| L3 claim/evidence graph (training-free) | **31.48%** (148 traces) | **40.04%** (1,000 cases) | **8.43%** (73 traces) | **Only layer to beat the baseline on all three corpora — the durable, generalizing win** |
| L4 meta-ranker, grouped OOF | 32.26% | 41.79% | 9.68% | Improves all three in-distribution |
| L4 meta-ranker, LODO | 28.74% (below claim graph) | 41.47% | 9.68% | **Fails to generalize on TRAIL** — not promoted as universal router |
| L5 hypothesis verifier, candidate recall (oracle) | 41.80%→46.11% | 38.05%→70.45% | 8.98%→20.06% | Accepted as a recall-only candidate generator |
| L6 category assignment (given oracle location) | 21.17% accuracy, 9.53% end-to-end joint F1 (below 11.41% baseline) | n/a (no category labels) | **64.97%** accuracy, 6.51% joint F1 | Accepted for AgentRx only |
| L7 frozen TRAIL-safe router (62/86 pre-registered split) | Selected holdout: 29.79% F1 (claim graph); meta-ranker counterfactual 34.25% (not actionable — would be leakage) | — | — | Demonstrates split instability; both partitions now spent |
| L8 repeated nested router (5×5×5 CV, 740 trace evaluations) | Always-claim-graph 31.48% vs. always-meta-ranker 33.12% vs. calibration-selected 31.52% | — | — | Meta-ranker wins by 1.64 F1 in aggregate, but **every 95% paired-bootstrap CI crosses zero** — not statistically established |
| L9 RootSE, untouched external zero-shot | n/a (different corpus) | — | — | 21/102 top-3 hits, 10.37% F1 vs. 10.15% baseline; ranking, not discovery, is the bottleneck |

### X1 semantic RAG judge (context, not a diagnosis layer — `.verify/reports/ragtruth-*`)

| Metric (untouched 2,128-record holdout at threshold 0.63) | Result |
|---|---:|
| Precision | 80.24% |
| Recall | 70.71% |
| F1 | 75.18% |

Passes the roadmap's ≥80% precision / ≥70% recall RAGTruth gate. It is advisory unless
`--semantic-gate` is explicitly supplied, and cross-domain (LLM-AggreFact/FaithBench) validation
remains open. Included here for completeness since it is the other probabilistic/model-based
diagnosis-adjacent signal in the codebase, not because it is part of the TRAIL diagnosis stack.

## Competitive landscape (preserve honestly)

- **Holistic Evaluation and Failure Diagnosis of AI Agents** (May 2026 paper) reports 61–64% on
  TRAIL, but uses GPT-5.4 and a precision-like metric different from TRAIL's official macro-recall
  scorer, and has no full public implementation to independently verify. Not directly comparable.
- **Pisama** claims 59.9% for heuristic detectors. This is a vendor-published result with a private
  mapper and a BSL (not fully open) license — should be independently reproduced before comparison,
  which has not happened.
- **MASPrism**'s artifact is currently unreproducible: its Zenodo v1.0.0 record is marked restricted
  with no downloadable files, and its linked GitHub repository returns 404. The independent
  paper-text reimplementation in this repo (Layer 2 above) is explicitly not claimed as a
  reproduction.

None of these headline numbers is directly comparable to the TRAIL-released scorer results in this
report. ReplayGuard's credible research target remains a reproducible hidden/domain-held-out result
with cost, latency, precision, and code disclosed — not a higher public-corpus headline.

## Conclusions

1. The tiny local model beats the TRAIL paper's reported Gemini figure on the public corpus but is
   **not statistically significant** in its improvement over the deterministic baseline once measured
   with a paired bootstrap, and it **does not generalize** across the GAIA/SWE-Bench domain split.
2. The claim/evidence graph (Layer 3) is the **only layer that improves standalone location F1 on
   every external corpus it was measured against** (TRAIL, TELBench, AgentRx) without training on
   any of them. It is training-free, makes no API calls, and cannot access gold labels or metadata.
   This is the durable result of the entire research arc.
3. The meta-ranker (Layer 4/8) improves in-distribution grouped out-of-fold scores but **fails
   leave-one-dataset-out on TRAIL**, and its aggregate 1.64-point win over the claim graph in the
   5-repeat nested evaluation has confidence intervals that cross zero in every repeat. It is a
   strong research configuration, not a validated universal default.
4. The hypothesis verifier reliably expands **candidate recall** (union oracle) on every corpus,
   confirming that after Layer 3, **candidate discovery/ranking — not generation — is the
   bottleneck**: even an oracle over the full candidate union recovers only 41.8–49.0% of TRAIL
   locations and 49.0% overall union coverage on RootSE.
5. The RootSE external zero-shot test (Layer 9, genuinely new corpus, zero tuning) confirms this:
   the meta-ranker roughly doubles top-3 hit coverage over the baseline but only nudges F1 because
   ranking, not discovery, is the limiting factor externally too.
6. None of the vendor/paper headline comparisons (Holistic Evaluation, Pisama, MASPrism) is
   apples-to-apples with this report's numbers; they should not be cited as direct benchmarks against
   ReplayGuard's results.

## Shipping vs. parking

**Ships now, as an explicit opt-in, non-gating signal:**
- The claim/evidence graph (`replayguard.claim_graph`), behind `verify diagnose --experimental-claim-graph`.
  It is the only result here that is (a) durable across three independent corpora, (b) training-free
  so it carries no dataset-license or drift risk, and (c) cheap (no GPU, no API calls). It ships
  labeled experimental and is explicitly excluded from the deterministic default and from any exit-code
  gate. See `docs/DIAGNOSE_CLAIM_GRAPH.md`.

**Stays research-only, not wired into any default or CLI path:**
- The tiny TF-IDF model and the deterministic+model hybrid (does not generalize cross-domain).
- The meta-ranker / nested router (fails LODO on TRAIL; gain over claim graph is not statistically
  established).
- The Qwen3-0.6B prefill-attribution pilot (not an accepted MASPrism reproduction; zero TRAIL matches).
- The hypothesis verifier and category-assignment layers (accepted as research findings — recall
  expansion and AgentRx category accuracy respectively — but not promoted to any product surface).
- The frozen TRAIL-safe router split and the RootSE external set are now spent for model selection
  and must not be reused as if they were fresh untouched gates in any future work.

## What this means for the roadmap

148 TRAIL traces have been mined through nine stacked layers, a tiny model, cross-domain transfer,
a frozen calibration split, a five-repeat nested CV, and one genuinely external corpus (RootSE). The
marginal information left in this benchmark is shrinking: the RootSE zero-shot result and the
crosses-zero confidence intervals on the meta-ranker both point the same direction — accuracy on a
148-trace benchmark is no longer the constraint. Getting the tool in front of real users and real
traces is. See `docs/ROADMAP_V2.md` for how this reprioritizes the roadmap.
