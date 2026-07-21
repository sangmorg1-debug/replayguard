# N1 OpenTelemetry trace bridge status

N1 is complete. The format bridge, full public-repository corpus gate, and separately authorized
Hugging Face acceptance gate are implemented and measured.

## Implemented

- Import standard OTLP/JSON `resourceSpans` envelopes.
- Import flat OpenTelemetry JavaScript span exports used by OpenInference fixtures.
- Import the nested JSON representation published in TRAIL's public MIT benchmark repository.
- Map model, tool, retrieval, agent, and artifact spans into ReplayGuard's canonical event kinds.
- Preserve trace/span IDs, parents, nanosecond source timestamps, span status, attributes and nested AnyValues, ordered events, links, resource attributes, instrumentation scope, trace state, flags, and unknown attributes.
- Decode common OpenInference and `gen_ai.*` input/output and token-usage fields without discarding their source attributes.
- Export canonical runs as standards-shaped OTLP/JSON.
- Produce convention-version and attribute-family coverage reports.
- Exact fixture replay of imported traces has no live-call path.

## Pinned conventions

- OTLP specification: 1.10.0.
- OpenTelemetry semantic conventions snapshot: 1.43.0.
- OpenInference adapter snapshot: repository commit `5290b7b34040c140682f620772b2d6cf406f1bad`.

These are adapter inputs, not claims that evolving GenAI conventions are stable forever. A convention change requires a new adapter version and compatibility fixtures.

## Real-data evidence

The default test corpus is the Apache-2.0 OpenInference Vercel v6 fixture `all-spans.json`, pinned at commit `5290b7b34040c140682f620772b2d6cf406f1bad` and SHA-256 `137ddd06ad9df4be684f316d485e5c6321a71ae2049f20b293caf3838fcac252`. All ten real upstream spans pass normalized semantic round-trip.

A public MIT TRAIL repository sample is fetched to ignored `.verify/upstream` at commit `0ffbed9db859b4a66250dc783fa4dccf86869595`, SHA-256 `a8b31d38493a22091788f99e32beb79b801e35269f626b6a0de0446f435df38e`. Its 11 recursively nested spans pass the same round-trip. This sample fetch does not access the gated Hugging Face files and is not bundled into the redistributable corpus.

The same pinned public repository now has a full-corpus gate. All 148 trace files available at that
revision (117 labeled GAIA and 31 labeled SWE Bench by the repository paths) import as 4,626
recursively expanded spans and round-trip with zero semantic mismatches. The verifier checks every
trace against the SHA-256 recorded by `fetch_trail_n2.py` before parsing it and emits aggregate plus
per-trace evidence.

On 20 July 2026, the authorized Hugging Face account fetched revision
`b424ce63d5973d5dcd7169b1bc3c07ccdee276d1` into ignored private cache storage after the access
conditions were accepted. The generated private manifest has SHA-256
`e1a907428909762a62b489142af2e93f6604924ecba2b7e95443c18e4f8d4094` and records SHA-256 for
all 148 trace/annotation pairs. The gated files independently produce the same measured result:
148 runs, 4,626 recursively expanded spans, and zero normalized semantic round-trip failures. The
pinned dataset contains 117 `GAIA` and 31 `SWE Bench` trace files. Those measured revision-specific
counts supersede the roadmap's earlier secondary-description figures of 118/30 and 1,987 spans.

```powershell
python tools/fetch_otel_data.py
python tools/benchmark_otel.py
python tools/fetch_trail_sample.py
python tools/benchmark_otel.py --trail
python tools/benchmark_otel.py --trail-corpus .verify/upstream/trail-n2 --output .verify/reports/n1-trail-public.json
python tools/fetch_trail_hf.py --output .verify/upstream/trail-hf
python tools/benchmark_otel.py --trail-corpus .verify/upstream/trail-hf --output .verify/reports/n1-trail-hf.json
verify otel roundtrip tests/data/public/openinference_otel_spans.json --output .verify/openinference.otlp.json
```

## Acceptance result

Every trace in both pinned representations imports and preserves IDs, parents, timestamps, status,
ordered events, links, known attributes, and opaque unknown attributes under normalized export.
Restricted Hugging Face files remain only in ignored private cache storage and are not bundled or
redistributed.

Raw byte identity is intentionally not a gate: JSON key order, protobuf JSON representation, and parquet encoding are not canonical. Normalized semantic identity is the meaningful compatibility requirement.
