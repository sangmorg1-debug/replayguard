# Phase 8 cost-per-success optimization completion record

Phase 8 engineering is complete. Production billing reconciliation and customer savings remain external validation gates.

## Implemented

- Provider/model-normalized input, cached-input, output, and per-request costing from an immutable price catalog.
- Explicit rejection of unknown model prices, negative usage, and impossible cache counts.
- Cost per successful task, quality score, success rate, Wilson 95% interval, latency, cache savings, retry cost, and security pass rate.
- Attribution by repository, feature, customer, agent, and task, including an explicit unattributed bucket.
- CI budgets for total cost and cost per verified success.
- Quality-, security-, and latency-constrained recommendations. An inexpensive configuration cannot be recommended if any configured constraint fails.
- Billing reconciliation with configurable tolerance; missing billing data cannot produce a passing reconciliation.
- Reports record the price-catalog version and effective date.

## Real public evaluation data

`tools/build_cost_benchmark.py` derives 200 candidate records from 100 real human comparisons in OpenAI's MIT-licensed `summarize-from-feedback` dataset already downloaded by Phase 2. Each pair retains its real human choice and policy metadata.

The public data does not contain API usage or invoices. Token counts are therefore visibly labeled `word-count approximation x1.3`, latency is recorded as unmeasured (`0`), and no billing-accuracy claim is made from this corpus. Production integrations should ingest provider-reported token counts and invoiced costs.

The immutable example catalog is a June 2025 reproducibility snapshot using official provider pricing pages. It must not be interpreted as current pricing; rates must be reviewed and a new catalog version committed before production decisions.

## Reproducible result

```powershell
python tools/build_cost_benchmark.py
python tools/benchmark_cost.py
verify cost analyze --records tests/data/cost-preference-records.json --catalog examples/price-catalog-2025-06.json --output .verify/cost-report.json
verify cost recommend --report .verify/cost-report.json --baseline candidate-1 --min-quality 0.45
```

On the pinned 100-comparison slice:

- Attribution coverage: 100%.
- Baseline human preference: 44%.
- Proposed human preference: 56%.
- Estimated baseline cost per success: $0.00040398.
- Estimated proposed cost per success: $0.00032256.
- Estimated verified cost-per-success reduction: 20.16%.

This is an experimental comparison over historical outputs, not evidence that changing a production model will reproduce the same outcome.

## Gate status

Engineering gates achieved:

- Provider-normalized deterministic cost calculation with cache and retry attribution.
- More than 90% of benchmark calls are attributed to a feature and task (measured: 100%).
- Recommendations enforce every configured quality, security, and latency constraint.
- The real-data experiment reduces estimated cost per human-preferred success by more than 20% without a measured quality reduction.
- Reports contain the baseline, proposal, quality difference, cost difference, latency difference, dataset size, confidence interval, and applicability conditions.
- Exported records and the versioned catalog reproduce every result.

External gates still requiring production users:

- Cost calculations agreeing with actual provider invoices within 5%. The reconciliation feature exists, but no invoice was supplied.
- Five teams running comparative cost evaluations.
- Three teams reproducing a 20% production cost-per-success reduction.
- No statistically significant quality regression after accepted production recommendations.
- Two customers paying specifically for optimization.

## Operational cautions

- Never silently fall back to a similarly named model when a catalog entry is missing.
- Model aliases and pricing catalogs must be versioned together.
- Provider-reported cached tokens should be used instead of inferred cache hits.
- Cost reductions are invalid if security or required quality constraints fail.
- Overlapping confidence intervals should be presented to users; they are not proof of equivalence or superiority.
