# Phase 2 completion record

## Implemented

- Promote successful or failed traces into positive/negative regression cases.
- Redact case content before suite persistence.
- Versioned suite format, grouping tags, parameters, baseline constraints, and case provenance.
- Comparison of structure, responses, tools and arguments, retrieval, authorization, artifacts, errors, steps, latency, and cost.
- Exact, JSON Schema, reference, token-cosine similarity, custom, human-review, pairwise, and model-graded evaluation methods.
- Explicit deterministic/probabilistic labels and evaluator versions on every result.
- Model-grader model, prompt version, votes, and limitations retained in output.
- Repeated-run pass rate, response/tool variance, cost/latency variance, Wilson 95% interval, and run-count estimate.
- Baseline budgets and prohibited-tool security invariants.
- CLI workflows: `verify suite create|add|run` and `verify flaky`.
- Reusable public suite generated from checksum-pinned BFCL, tau2-bench, and AgentDojo records.
- Real execution evidence: three recorded tau2 full-duplex simulations with thousands of timestamped interaction ticks.
- Real human evidence: 100 OpenAI summarization comparisons containing actual model outputs, crowd-worker choices, and confidence metadata.

## Automated gate evidence

- Public/internal corpus exceeds 100 reusable cases.
- Seeded structural-regression detection: 100% in the controlled 100-case test.
- Deterministic false-alarm rate: 0% in the controlled unchanged cases.
- Deterministic failures cannot be overridden by probabilistic graders.
- Every result records its inputs through the source run, evaluator method/version, suite configuration, and case ID.
- The complete automated test suite runs well below the two-minute 25-case target on the development machine.

## External gates still pending

The following cannot be honestly automated from public data: five teams maintaining suites, three teams using them before real changes, two teams reporting prevented deployments, and 80% model-grader agreement with human reviewers. Model graders are supported but remain non-authoritative until a labeled human-review study establishes that agreement.

Public human labels now support an honest grader-agreement experiment via `python tools/analyze_human_preferences.py`; simple deterministic heuristics are reported as baselines, not presented as model graders.
