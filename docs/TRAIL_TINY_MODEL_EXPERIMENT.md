# TRAIL tiny local model experiment

> Consolidated alongside `STACKED_DIAGNOSTICS_EXPERIMENT.md` in
> [`RESEARCH_TRAIL_DIAGNOSIS.md`](RESEARCH_TRAIL_DIAGNOSIS.md), which is the current source of truth
> for what ships vs. stays research-only. This document remains the detailed record of this
> experiment's protocol and results.

## Outcome

A CPU-only TF-IDF plus one-vs-rest logistic model, evaluated with five-fold out-of-fold prediction
grouped by complete trace, reaches 14.91% strict macro joint span/category accuracy. Combining its
top two candidates with one frozen deterministic ReplayGuard candidate reaches an exploratory
19.40%. The experiment is reproducible: two complete runs returned identical metrics.

| System | Macro joint | Pair precision | Micro recall | Pair F1 |
|---|---:|---:|---:|---:|
| Frozen deterministic, top 3 | 14.94% | 17.90% | 8.37% | 11.41% |
| Tiny local model, out-of-fold top 3 | 14.91% | 29.95% | 15.91% | 20.78% |
| Exploratory hybrid, top 3 | 19.40% | 29.95% | 15.91% | 20.78% |

The hybrid has the same total matches as the model but distributes them across traces differently;
TRAIL's official headline is a per-trace macro recall, so its macro score is higher. Precision and
F1 are reported to prevent that metric from being read alone.

## Protocol and leakage controls

- Dataset: authorized `PatronusAI/TRAIL` revision
  `b424ce63d5973d5dcd7169b1bc3c07ccdee276d1`; private manifest SHA-256
  `e1a907428909762a62b489142af2e93f6604924ecba2b7e95443c18e4f8d4094`.
- Five folds are assigned by SHA-256 of trace ID. Every prediction is made by a model that did not
  train on that complete trace. No spans from a trace cross its fold boundary.
- Features use canonical name, kind, status, position, parent presence, request, response, and error.
  `Event.attributes`, preserved raw spans, and `trail.annotations` are never feature inputs because
  the gated files contain annotation metadata there.
- Model and candidate limit are fixed in `MODEL_SPEC`; random seed is `20260720`.
- Predictions are emitted in the official TRAIL JSON format. The pinned upstream scorer is run
  unchanged at SHA-256 `ed81ebd…`; Python UTF-8 mode is required on Windows.
- One upstream annotation has invalid trailing-comma JSON. The official scorer silently skips it;
  ReplayGuard's strict 148-trace metric applies the existing documented repair and reports the file.

This is not a pristine hidden-set result: the public benchmark and its annotations had already been
inspected while building the deterministic engine. Out-of-fold training prevents direct trace
memorization by the model, but only an external hidden evaluation can support a leaderboard claim.

## Generalization result

Domain transfer is the current blocker:

| Train → test | Macro joint | Precision | F1 |
|---|---:|---:|---:|
| GAIA → SWE Bench | 6.04% | 17.20% | 9.20% |
| SWE Bench → GAIA | 0.97% | 1.99% | 1.50% |

The cross-validation gain therefore contains substantial within-domain learning. The next model
iteration should target transferable structural features and additional independently labeled trace
corpora, not tune further on TRAIL.

## Competitive interpretation

Beating the original paper's roughly 11% combined Gemini 2.5 Pro Preview result is useful evidence
that trace decomposition plus inexpensive local inference can outperform monolithic long-context
prompting. It is no longer a state-of-the-art claim. The May 2026 *Holistic Evaluation and Failure
Diagnosis of AI Agents* paper reports much larger gains on TRAIL from per-span evaluation, and
Pisama claims 59.9% for heuristic detectors. The latter is a vendor-published result and should be
independently reproduced before comparison.

ReplayGuard's credible research target is a reproducible hidden/domain-held-out result with local
cost, latency, precision, and code disclosed—not merely a higher public-corpus headline.

## Reproduce

```powershell
pip install -e ".[experiment]"
python tools/fetch_trail_hf.py --output .verify/upstream/trail-hf
python tools/experiment_trail_tiny.py --corpus .verify/upstream/trail-hf --output .verify/trail-tiny-experiment
python tools/score_trail_official.py --corpus .verify/upstream/trail-hf --predictions .verify/trail-tiny-experiment/official_predictions
```

Restricted dataset files and trained artifacts remain under ignored `.verify`; they must not be
redistributed.
