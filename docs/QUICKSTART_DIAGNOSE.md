# Quickstart: your traces → replay → ranked suspects

This walks through the lead wedge end to end using only a public, non-gated sample — no Hugging
Face access, no API keys, nothing installed beyond the base package. Every command below was
actually run to produce the output shown; nothing here is hypothetical.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

## 1. Import a real OpenTelemetry trace export

`tests/data/public/openinference_otel_spans.json` is a real, Apache-2.0-licensed 10-span sample
from the OpenInference Vercel AI SDK adapter (pinned commit `5290b7b34040c140682f620772b2d6cf406f1bad`).
This is the same shape of file a Langfuse/Arize/Datadog OTLP export produces — that's the point:
point ReplayGuard at what you already have.

```powershell
verify --store .verify\quickstart otel import tests\data\public\openinference_otel_spans.json
```

```json
{
  "imported_runs": ["045d21a7f69972edf509fe0ff911f3f5", "91621bbaaf1920e94ae594e91b3a99fd", "..."],
  "adapter_version": "otel-1.0.0",
  "conventions": {"otlp": "1.10.0", "otel_semconv": "1.43.0", "openinference": "2026-07-snapshot"},
  "runs": 10,
  "spans": 10
}
```

Ten spans became ten local runs, fully offline. Nothing was sent anywhere; the import is a pure
format conversion into ReplayGuard's schema.

## 2. Rank suspect spans

```powershell
verify --store .verify\quickstart diagnose 045d21a7f69972edf509fe0ff911f3f5 --experimental-claim-graph
```

```json
{
  "run_id": "045d21a7f69972edf509fe0ff911f3f5",
  "inspected_spans": 1,
  "suspects": [],
  "experimental_claim_graph": [
    {
      "span_id": "53e12604843b0399",
      "category": "Unclassified",
      "score": 0.9,
      "reason": "A consequential claim has weak or missing earlier evidence and may propagate into later steps.",
      "evidence": "[CLAIM001] kind=model name=ai.embed.doEmbed status=ok request= response= error=",
      "deterministic": false
    }
  ]
}
```

This particular sample is a clean, successful trace, so the deterministic engine's `suspects` list
is correctly empty — there's no error signature to find. The `--experimental-claim-graph` flag
still surfaces one advisory lead (an unsupported commitment) because that signal runs independent of
whether the trace failed; it is non-gating and never changes the CLI's exit code either way. Try it
against one of your own failing traces to see `suspects` populate with span IDs, TRAIL categories,
confidence, and evidence.

## What this is (and isn't) telling you

- `suspects` (deterministic) is the production default: reproducible, benchmarked against TRAIL's
  148 human-annotated traces (17.84% macro joint accuracy, 10.24% precision — see
  `docs/N2_FAILURE_LOCALIZATION.md`), and safe to build automation on.
- `experimental_claim_graph` is opt-in and advisory: a training-free signal that generalized across
  three independent benchmark corpora in research (`docs/RESEARCH_TRAIL_DIAGNOSIS.md`,
  `docs/DIAGNOSE_CLAIM_GRAPH.md`) but has not been validated on real production traces. Treat it as
  a lead worth a look, not a finding.
- Both run entirely locally against fixture-only replay. No live model or tool call happens during
  diagnosis.

## Next steps

- Wire your own OTLP exporter's output into `verify otel import` the same way.
- Turn a set of runs into a regression suite with `verify suite create` / `verify suite add`, then
  gate PRs on it — see the root `README.md`'s "GitHub Action and local CI" section.
- If you hit a real failure and want to compare ReplayGuard's ranking against what you already knew,
  that's exactly the kind of session `docs/L5_EXTERNAL_VALIDATION.md` is trying to capture.
