# N2 failure localization baseline

`verify diagnose RUN_ID` now ranks deterministic span/category suspects and can score them
against a TRAIL processed-annotation file:

```powershell
verify --store .verify diagnose RUN_ID --ground-truth annotation.json
```

The initial engine localizes observable API failures, missing required delimiters, invalid
required JSON, unsupported claims of retrieved evidence, abandoned retrieval plans, and repeated
tool-call abuse. Every result includes the span ID, TRAIL category, confidence, reason, and compact
evidence. It does not call an LLM or a live tool.

## Reproducible real-data benchmark

The corpus is fetched from the public `patronus-ai/trail-benchmark` repository at commit
`0ffbed9db859b4a66250dc783fa4dccf86869595`. Nothing is generated or vendored. The downloader
records the upstream path and SHA-256 of every file under the ignored `.verify/` directory.

```powershell
python tools/fetch_trail_n2.py
python tools/benchmark_trail_n2.py
```

Baseline measured 2026-07-19 on all 148 repository traces (117 GAIA, 31 SWE-Bench at the pinned revision):

| Metric | Result |
|---|---:|
| Official macro span+category joint accuracy | 17.84% |
| 95% trace-bootstrap interval | 13.79%–22.14% |
| Unique human span/category pairs in public processed files | 836 |
| Micro matched pairs | 91 / 836 (10.89%) |
| Pair precision | 10.24% |
| Pair F1 | 10.55% |
| Deterministic execution/API subset | 4 / 134 (2.99%) |

## Precision-hardening result

After the authorized gated corpus became available, candidate-count tuning was confined to a
deterministic 21-trace calibration partition selected by SHA-256 of trace ID. The remaining 127
traces were held out. A three-candidate default was selected to reduce suspect spam; callers can
still explicitly request a larger list with `--max-candidates`.

| Metric | Calibration | Untouched holdout | Full corpus |
|---|---:|---:|---:|
| Traces | 21 | 127 | 148 |
| Pair precision | 18.87% | 17.75% | 17.90% |
| Micro pair recall | 8.93% | 8.29% | 8.37% |
| Pair F1 | 12.12% | 11.30% | 11.41% |
| Macro joint span+category accuracy | 11.11% | 15.57% | 14.94% |

The original full-corpus baseline emitted 889 candidates; the hardened default emits 391. Precision
therefore improves from 10.24% to 17.90% and F1 from 10.55% to 11.41%, at the cost of recall. The
execution/API subset falls to 1/134 under the three-candidate cap because those human labels are
usually attached to successful LLM reasoning spans rather than explicit failed tool spans. This
tradeoff is acceptable for a concise advisory ranking, but it is not evidence for an automated gate.
The reproducible result is `.verify/reports/trail-n2-hardened.json`.

The official upstream metric averages per-trace recall and does not penalize false positives.
Therefore the README-quality claim must include precision and F1; the 17.84% number must never be
presented alone. The upstream README says 841 errors, while the 148 processed annotation files at
the pinned public commit contain 836 unique span/category pairs. One annotation also has a trailing
comma; the loader applies only a trailing-comma repair and otherwise preserves its contents.

This completes a reproducible N2 baseline, held-out precision-hardening pass, and CLI. The still-low
17.75% holdout precision and weak execution/API subset remain explicit blockers for recommending
the engine as an automated failure gate. Future semantic rules must improve held-out precision and
recall rather than exploit the recall-only official score.
