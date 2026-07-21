# L2 sampled OTLP tap — engineering preview

This feature is implemented but not production-validated. The roadmap's design-partner gate is
still open. It should be treated as a local engineering preview until real operational demand,
retention requirements, and deployment constraints have been validated.

Start a loopback-only OTLP/HTTP JSON receiver:

```console
verify tap --tap-store .verify/tap --suite .verify/production-suite.json \
  --sample-rate 0.01 --port 4318
```

Configure an OpenTelemetry exporter with
`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces` and protocol `http/json`.
Binding to any non-loopback address requires `--token`; clients then send
`Authorization: Bearer <token>`.

Safety and capacity behavior:

- Sampling is deterministic from the trace ID. Repeated delivery makes the same decision.
- Error traces bypass probabilistic sampling by default; use `--no-always-sample-errors` only
  after considering failure-coverage loss.
- Sensitive attribute keys and secret-shaped values are redacted before the OTLP adapter can
  preserve raw-span metadata, then redacted again before storage and suite creation.
- Request bytes, spans, traces, and concurrent requests are bounded. Capacity exhaustion returns
  HTTP 429 with `Retry-After: 1`; oversize requests return 413.
- OTLP partial-success responses report spans discarded by sampling or the trace limit. Counters
  are available locally at `/metrics`; `/healthz` reports preview status.
- Only OTLP/HTTP JSON traces are accepted. Metrics, logs, protobuf, gRPC, dashboards, general
  querying, and remote hosting are deliberately outside this feature.

The wire contract follows stable OTLP 1.10.0: HTTP POST `/v1/traces`, JSON protobuf mapping,
HTTP 200 success, and `partialSuccess.rejectedSpans` for partial acceptance. Tests use the
checksum-pinned Arize OpenInference Vercel span fixture already recorded in the public corpus.
