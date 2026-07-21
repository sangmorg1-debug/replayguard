# Stacked diagnostics experiment

> Consolidated alongside `TRAIL_TINY_MODEL_EXPERIMENT.md` in
> [`RESEARCH_TRAIL_DIAGNOSIS.md`](RESEARCH_TRAIL_DIAGNOSIS.md), which is the current source of truth
> for what ships vs. stays research-only. This document remains the detailed layer-by-layer record.

ReplayGuard will evaluate candidate-generation and verification layers across three independently
annotated corpora instead of optimizing only for TRAIL. This document records the first completed
gate: immutable, leakage-safe ingestion of the external evaluation data.

## Pinned public corpora

- **TELBench:** `NJU-LINK/TELBench` revision
  `307d870d7424be265653bb7a566793cc217105be`, Apache-2.0. The upstream encrypted release is
  downloaded, its encrypted checksum verified, decrypted with the upstream public passphrase using
  its specified AES-256-CBC/PBKDF2 parameters, and its plaintext checksum verified. Gold and
  annotations are never included in the model-input object.
- **AgentRx:** `microsoft/AgentRx` revision
  `f228165bfec60a801fd5fedd9d8ffe0f9de0c69d`, MIT. Public tau-retail and Magentic-One
  trajectories are joined to human ground truth by upstream trajectory ID. Original step numbers
  are preserved.

Run `python tools/fetch_diagnostic_corpora.py`, followed by
`python tools/audit_diagnostic_corpora.py`. Raw corpora live under ignored `.verify` storage and
are not redistributed by ReplayGuard.

## Metric boundary

The three datasets do not measure the same target. TRAIL evaluates joint span and taxonomy-category
recovery; TELBench evaluates harmful error-span localization; AgentRx evaluates step localization
and its own ten-category taxonomy. Scores remain separate. The primary generalization gate will be
leave-one-dataset-out performance, with precision, recall, F1, candidate budget, latency, hardware,
and model/API cost reported for every layer.

## Next implementation gate

Implement a common candidate record (`location`, optional `category`, confidence, evidence, signal
type), then add three independently implemented layers in this order: AgentRx-style deterministic
schema/policy invariants, MASPrism-style Qwen3-0.6B prefill attribution, and a local DRIFT-style
claim/evidence graph. A calibrated meta-ranker may combine candidates; blind union is prohibited
because it can inflate recall-like benchmark scores through false positives.

## Layer 1 result: deterministic invariants

Implemented in `replayguard.diagnostic_candidates` and `replayguard.invariants`. The common record
contains location, optional category, confidence, signal type, and one or more structured evidence
records with a stable rule ID. The first invariant set covers malformed and unmatched tool calls,
mixed content/tool responses, explicit tool failures, repeated-call loops, consequential actions
without confirmation, and private/state-changing actions before authentication.

`tools/benchmark_stacked_invariants.py` evaluates a strict top-three budget. Its conservative stack
keeps ReplayGuard's calibrated baseline ordering, enriches overlapping locations with invariant
evidence, and uses invariants only to fill otherwise unused slots. This avoids the measured failure
mode where incomparable raw confidence values displaced better baseline candidates.

Measured on the pinned complete corpora:

| Corpus / native target | Baseline F1 | Invariants F1 | Conservative hybrid F1 | Result |
|---|---:|---:|---:|---|
| TRAIL joint span+category | 11.41% | 0.74% | 11.12% | no recall gain; filled candidates reduce precision |
| TELBench span localization | 13.13% | 14.09% | 20.50% | useful complementary signal |
| AgentRx step localization | 1.07% | 3.85% | 4.49% | useful but low recall |
| AgentRx joint step+category | 0.00% | 1.65% | 1.50% | correct locations improve; taxonomy remains weak |

The first layer therefore validates the stacking architecture but is not a universal improvement.
It is retained as an auditable feature/candidate source, not promoted as a new TRAIL headline. The
next layer should target semantic localization—MASPrism-style small-model prefill attribution—then
calibrate a meta-ranker on out-of-fold predictions instead of adding more uncalibrated candidates.

## Layer 2 result: Qwen3-0.6B prefill attribution pilot

`replayguard.prefill_attribution` implements an independent, zero-decode, two-prefill-pass method
from the MASPrism paper text: step NLL identifies symptoms, attention over the final 20% of layers
routes to earlier candidates, a focused second prompt restores candidate/symptom details, and NLL
contrast plus multi-symptom consensus produces the ranking. It emits the common candidate/evidence
contract. `tools/benchmark_prefill_attribution.py` is resume-safe and pins Qwen3-0.6B revision
`c1899de289a04d12100db370d81485cdf75e47ca`.

This is **not a successful MASPrism reproduction**. On 20 July 2026, the paper's Zenodo v1.0.0
record was marked restricted with no downloadable files, and its linked GitHub repository returned
404. Consequently, implementation details absent from the rendered equations could not be audited.
The local experiment also uses a GTX 1660 Ti (6 GB), CUDA 12.8, PyTorch 2.7.1, and a 2,048-token
eager-attention cap rather than the paper's RTX 5090 environment. Adaptive compression retains every
step but shortens content to fit. Two of 34 attempted TRAIL cases still exceeded the cap.

The initial real-data pilot processed 32 TRAIL, 30 TELBench, and 30 AgentRx traces successfully:

| Native location target | Baseline F1 | Prefill F1 | Conservative hybrid F1 |
|---|---:|---:|---:|
| TRAIL (location only, not joint) | 41.84% | 0.00% | 24.19% |
| TELBench | 38.30% | 33.96% | 41.51% |
| AgentRx | 0.00% | 3.03% | 1.52% |

TELBench shows complementary location signal, but the zero TRAIL matches sharply contradict the
paper's reported location results. This likely reflects an unrecovered candidate-selection,
serialization, or scoring detail; it is not evidence that the published method is ineffective.
The layer must not enter the production hybrid or headline comparison. The raw pilot remains in
`.verify/reports/prefill-attribution-pilot-30.json`; the complete-corpus runner can resume once the
official artifact is accessible or the discrepancy is independently resolved.

## Layer 3 result: local claim/evidence graph

`replayguard.claim_graph` independently implements the claim-centric architecture without copying
DRIFT's LLM prompts or claiming equivalent behavior. It extracts explicit consequential/finalized
commitments, links them to earlier evidence using rarity-weighted lexical overlap, discounts pure
search/probe spans, identifies weakly supported claims, and propagates risk to later reuse/finalization
locations. Every result carries a `CLAIM001` evidence record with the claim excerpt and linked
support/reuse locations. It is training-free, makes no API calls, and cannot access gold or metadata.

`tools/benchmark_claim_graph.py` completed all pinned public cases under a top-three location budget:

| Native location target | Baseline F1 | Invariants F1 | Claim graph F1 | Conservative hybrid F1 |
|---|---:|---:|---:|---:|
| TRAIL, 148 traces / 579 unique locations | 27.79% | 8.54% | **31.48%** | 28.06% |
| TELBench, 1,000 / 2,552 labels | 13.13% | 14.09% | **40.04%** | 39.14% |
| AgentRx, 73 / 334 labels | 1.02% | 3.85% | 8.43% | **9.70%** |

The claim graph is the first new layer to improve standalone location F1 on every external corpus.
Baseline-first conservative stacking is now demonstrably the wrong universal policy: it helps
AgentRx but displaces stronger claim candidates on TRAIL and TELBench. The next experiment should
generate out-of-fold candidate features and fit a cross-dataset calibrated router/meta-ranker,
with leave-one-dataset-out results as the primary generalization gate. Category assignment remains
separate; these are location-only results and are not the TRAIL joint headline metric.

## Layer 4 result: calibrated meta-ranker

`replayguard.meta_ranking` builds 13 label-free features from baseline, invariant, and claim-graph
scores/ranks, signal agreement, relative position, text length, explicit-error/commitment markers,
and linked-evidence count. `tools/experiment_meta_ranker.py` fits a weighted logistic router under a
strict top-three budget. Labels are attached only after feature construction. Five-fold evaluation
groups complete traces, and leave-one-dataset-out (LODO) evaluation trains on the other two corpora
without any examples from the held-out dataset.

| Corpus | Best standalone F1 | Mixed-corpus grouped OOF | LODO | Candidate-union oracle recall |
|---|---:|---:|---:|---:|
| TRAIL | 31.48% claim graph | **32.26%** | 28.74% | 41.80% |
| TELBench | 40.04% claim graph | **41.79%** | **41.47%** | 38.05% |
| AgentRx | 8.43% claim graph | **9.68%** | **9.68%** | 8.98% |

The grouped OOF result improves all three datasets, showing that calibration can recover useful
cross-signal ordering. The stronger LODO gate does not pass universally: transfer improves TELBench
and AgentRx but underperforms the standalone claim graph on held-out TRAIL. Therefore the router is
an experiment, not the production default. Candidate coverage is now the main bottleneck: even an
oracle over the current union can recover only 8.98% of AgentRx labels and 41.80% of TRAIL locations.
The next layer should expand recall through error-first hypothesis generation/verification before
another ranking pass; merely changing the ranker cannot recover locations no generator proposes.

## Layer 5 result: error-first hypothesis verification

`replayguard.hypothesis_verification` implements a training-free VerifyMAS-inspired decomposition
without claiming reproduction of its fine-tuned verifier. It identifies explicit failures, aborts,
and consequential commitments first; generates backward source hypotheses using trace-wide lexical
relations; and records entail/neutral/contradict verdicts with `HYP001` evidence. Contradicted
hypotheses are removed. Up to eight verified locations form a recall-oriented candidate pool; the
meta-ranker output remains capped at three.

| Corpus | Old union oracle recall | Expanded oracle recall | Old grouped OOF F1 | Expanded grouped OOF F1 | Expanded LODO F1 |
|---|---:|---:|---:|---:|---:|
| TRAIL | 41.80% | **46.11%** | 32.26% | **32.45%** | 23.85% |
| TELBench | 38.05% | **70.45%** | 41.79% | **49.41%** | **49.38%** |
| AgentRx | 8.98% | **20.06%** | 9.68% | **13.02%** | **11.57%** |

The recall objective succeeds on every corpus and produces large TELBench/AgentRx gains under the
same top-three ranking budget. TRAIL cross-dataset transfer deteriorates further even though its
within-corpus grouped OOF result improves slightly. The verifier is therefore a validated candidate
generator, while the learned router remains non-universal. The next useful work is category
assignment for the stronger locations and/or a TRAIL-safe routing policy evaluated on a frozen
holdout; further broad candidate expansion alone risks reducing precision.

## Layer 6 result: native-taxonomy category assignment

`replayguard.category_assignment` and `tools/experiment_category_assignment.py` assign one native
failure category after localization. The benchmark fits a sparse TF-IDF/SGD log-loss classifier in
five trace-grouped folds; category labels from a held-out trace never enter its training set.
TRAIL and AgentRx are trained and reported separately because their taxonomies differ. TELBench is
correctly excluded because it provides locations but no failure-category labels.

| Corpus | OOF top-3 location F1 | Category accuracy at oracle locations | End-to-end joint F1 |
|---|---:|---:|---:|
| TRAIL, 148 traces / 836 normalized gold pairs | 32.26% | 21.17% | 9.53% |
| AgentRx, 73 trajectories / 334 gold pairs | 12.66% | **64.97%** | **6.51%** |

The category layer is useful for AgentRx once localization succeeds, raising the earlier joint
result from near zero. It does not clear the TRAIL gate: its 9.53% micro joint F1 is below the
existing deterministic baseline's 11.41%, and only 61 of 836 gold pairs match end to end. The
layer therefore remains experimental and taxonomy-specific. The next gate is a frozen TRAIL-safe
routing policy: it must fall back to the claim graph unless a calibration-only decision rule can
demonstrate improvement on an untouched trace-grouped holdout.

## Layer 7 result: frozen TRAIL-safe routing gate

`replayguard.routing_gate` and `tools/experiment_trail_safe_router.py` pre-register a deterministic
SHA-256 split: 62 TRAIL traces for calibration and 86 untouched traces for one-shot holdout. The
challenger must improve calibration F1 by at least one absolute point without losing precision;
otherwise the claim graph is selected. External TELBench and AgentRx cases may train the challenger
but never decide or score the TRAIL gate.

| Partition | Claim graph F1 | Meta-ranker F1 | Claim graph precision | Meta precision |
|---|---:|---:|---:|---:|
| Calibration, 62 traces | **33.71%** | 31.89% | **39.78%** | 37.63% |
| Frozen holdout, 86 traces | 29.79% | **34.25% counterfactual** | 33.72% | **38.76% counterfactual** |

Calibration therefore freezes the claim graph, and the selected holdout result is 29.79% location
F1. The challenger happens to perform better on holdout, but that observation cannot be used to
change the frozen decision without leaking the test result into policy selection. This is evidence
that a single calibration split is unstable, not permission to claim the counterfactual result as
the routed system. The safe production fallback is now explicit and tested. Any next router study
must use repeated nested cross-validation or a newly sourced external corpus; these 86 traces are
spent for model selection and must not be reused as another untouched gate.

## Layer 8 result: repeated nested router evaluation

`tools/experiment_nested_router.py` runs five repetitions of nested five-by-five trace-grouped
cross-validation. Each of 25 outer folds chooses its policy solely from inner-fold calibration;
TELBench and AgentRx may supply training examples but never TRAIL test labels. This is an estimator
of selection stability, not a replacement untouched holdout.

| Policy across 5 repeats / 740 trace evaluations | Precision | Recall | Location F1 |
|---|---:|---:|---:|
| Calibration-selected router | 36.31% | 27.84% | 31.52% |
| Always claim graph | 36.26% | 27.81% | 31.48% |
| Always TRAIL-calibrated meta-ranker | **38.15%** | **29.26%** | **33.12%** |

The gate selects the meta-ranker in 18 of 25 outer folds, yet its aggregate gain over always using
the claim graph is only 0.04 F1 points. The always-meta control beats the claim graph in each of the
five repeats and by 1.64 points in aggregate. Thus the per-split admission rule—not merely the
ranker—is unstable and supplies no meaningful benefit. A TRAIL-calibrated ranker is the best
research configuration, but the earlier leave-one-dataset-out collapse still prohibits calling it
a universal production router.

Ten thousand trace-paired bootstrap resamples per repetition put the meta-minus-claim point estimate
above zero in all five repetitions, but every 95% interval crosses zero (for example, repeat 0 is
-1.36 to +5.34 F1 points). Thus the observed 1.64-point aggregate advantage is promising but not
statistically established at 95% confidence on 148 traces. During this rerun, unstable iteration of
token `frozenset`s was also found in claim similarity; sorted `math.fsum` now removes that
per-process hash-order dependence. The next generalization gate requires genuinely new labeled
traces rather than another reuse of TRAIL.

## Layer 9 result: untouched RootSE external validation

RootSE is integrated at pinned Hugging Face revision
`c3e54cf25f99eddd85d8c9cbe3f41528e5e7f957` under its declared MIT license. It contributes 102
real failed repository-level coding-agent trajectories from four agent systems and seven model
configurations, each with one human-annotated earliest decisive error step. The leakage-safe reader
uses dataset-relative paths as trajectory IDs because four SWE tasks occur under multiple agent
runs; using task ID alone would silently collide predictions.

`tools/benchmark_rootse.py` trains the existing meta-ranker on TRAIL, TELBench, and AgentRx only,
then evaluates RootSE once without tuning on its inputs or labels.

| Method | Candidate budget | Earliest-step hits / 102 | Precision | Location F1 |
|---|---:|---:|---:|---:|
| ReplayGuard baseline | up to 3 | 10 | 10.53% | 10.15% |
| Deterministic invariants | up to 3 | 14 | 4.93% | 7.25% |
| Claim graph | up to 3 | 11 | 5.00% | 6.83% |
| Hypothesis generator | up to 8 | 41 | 5.33% | 9.41% |
| Meta-ranker, leave-RootSE-out | 3 | **21** | 6.93% | **10.37%** |

The meta-ranker doubles top-three earliest-step coverage over the under-filled baseline, but its F1
gain is only 0.22 points because it emits almost the full three-candidate budget. This is not strong
external confirmation of the TRAIL gain. The union of all candidate layers contains the gold step
for 49.02% of traces, while the ranker recovers 20.59%, making coding-domain ranking the immediate
bottleneck. RootSE must now remain an external test set; any RootSE-tuned router needs a new nested
protocol and cannot call these results untouched again.
