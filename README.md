# ReplayGuard

Point ReplayGuard at OpenTelemetry traces you already have (Langfuse, Arize, Datadog, or any OTLP
export), replay them offline with zero live side effects, and get ranked failure suspects. No
re-instrumentation required. That is the wedge: **replay + failure diagnosis on existing traces**,
benchmarked against Patronus AI's TRAIL dataset of 148 real human-annotated agent failures.
Everything else below (security scanning, the runtime gateway, RAG provenance, cost analysis, the
compliance pack, the TypeScript SDK) is supporting surface around that one thing, not a second
product. Start with [docs/QUICKSTART_DIAGNOSE.md](docs/QUICKSTART_DIAGNOSE.md), a runnable, verified
walkthrough using a public, non-gated sample trace.

**Honest status:** every feature below is engineering-complete, but ReplayGuard has not yet been
independently security-reviewed or used by a real design partner on a real failure; see
[docs/L5_EXTERNAL_VALIDATION.md](docs/L5_EXTERNAL_VALIDATION.md), the project's current top
priority. Current roadmap: [Roadmap v2](docs/ROADMAP_V2.md).

Implementation detail: [N1 OpenTelemetry bridge](docs/N1_OTEL_BRIDGE.md), the
[N2 failure-localization baseline](docs/N2_FAILURE_LOCALIZATION.md), and the consolidated
[TRAIL diagnosis research report](docs/RESEARCH_TRAIL_DIAGNOSIS.md). Import/export traces with
`verify otel`, then rank suspect spans with `verify diagnose RUN_ID` (add
`--experimental-claim-graph` for an opt-in research signal; see
[docs/DIAGNOSE_CLAIM_GRAPH.md](docs/DIAGNOSE_CLAIM_GRAPH.md)).

Pytest-native recording and exact replay are available through the automatically discovered
[N3 pytest plugin](docs/N3_PYTEST_PLUGIN.md).

ReplayGuard is a local-first Python SDK and `verify` CLI for capturing AI/model and tool interactions, replaying them from fixtures without external side effects, and comparing behavior. Payload content is **off by default**; hashes and metadata are retained after local redaction.

## Quick start

Requires Python 3.11+.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\verify init
.venv\Scripts\verify record examples/quickstart.py --capture-content
.venv\Scripts\verify inspect
```

Copy the run ID printed by `record`, then:

```powershell
.venv\Scripts\verify replay RUN_ID
.venv\Scripts\verify inspect RUN_ID
```

The Python SDK also works directly with `Recorder`, `@model_call`, and `@tool_call`. Exact replay never calls a live adapter. Selective/comparative modes require callers to explicitly supply both an adapter and an allowlisted operation name.

## Real public benchmark tests

The default offline suite includes checksum-verified subsets of BFCL v4, tau2-bench, and AgentDojo. It exercises more than 70 public tool-use, policy, and untrusted-content records. To re-download all sources from their pinned commits and verify the original byte checksums:
It also includes 100 real OpenAI human-feedback comparisons and three recorded tau2 full-duplex simulations; these contain actual model outputs, human choices, confidence metadata, timestamps, and interaction outcomes rather than generated test substitutes.

```powershell
$env:REPLAYGUARD_VERIFY_PUBLIC_DATA = "1"
python -m pytest tests/test_real_data.py -m network
```

`python tools/fetch_real_data.py` regenerates the vendored subsets only when every upstream checksum matches its manifest.

## Regression suites and flakiness

```powershell
verify suite create my-suite.json --name my-agent
verify suite add my-suite.json RUN_ID
verify suite run my-suite.json
verify flaky RUN_ID_1 RUN_ID_2 RUN_ID_3
```

Generate the bundled 100+ case public suite with `python tools/build_public_suite.py`. Phase 2 implementation and gate evidence are recorded in `docs/PHASE2.md`.

## GitHub Action and local CI

The repository includes a fork-safe composite Action and example workflow. The Action publishes a Markdown job summary, machine-readable results, and a hash-addressed evidence bundle while returning a required-check-compatible exit status.

Run the same gate without GitHub:

```powershell
verify ci --suite examples/public-regression-suite.json --output .verify/report
```

With Docker and `act` installed, run the actual smoke workflow locally:

```powershell
act workflow_dispatch -W .github/workflows/replayguard-act.yml
```

Phase 3 implementation, security decisions, and remaining external gates are documented in `docs/PHASE3.md`.

## Self-hosted private beta

```powershell
$env:REPLAYGUARD_MASTER_KEY = python -c "import secrets; print(secrets.token_urlsafe(48))"
verify serve --allow-bootstrap --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787/docs`, create the initial workspace, securely save its one-time API key, and restart without `--allow-bootstrap`. See `docs/PHASE4.md` and `docs/PRIVACY.md` before using sensitive data.

## MCP compatibility and security scanner

Scan an exported `tools/list` manifest without starting a server:

```powershell
verify mcp-scan --tools tools.json --output .verify/mcp-scan --fail-on high
```

Statically sweep every distribution manifest in the official MCP Registry without installing or
connecting to listed servers:

```powershell
verify mcp-scan --registry --output .verify/mcp-registry --fail-on critical
```

See the aggregate-only [N4 registry sweep record](docs/N4_MCP_REGISTRY_SWEEP.md). Registry
manifests do not contain `tools/list`, so this mode makes no tool-level security claim.

A revision-pinned semantic RAG judge is available through `pip install -e ".[semantic]"` and
`verify rag evaluate --semantic`. Its calibrated RAGTruth holdout result is 80.24% precision and
70.71% recall. It remains advisory unless `--semantic-gate` is explicitly supplied; see
[X1 semantic judge](docs/X1_SEMANTIC_JUDGE.md) for scope and cross-domain limitations.

Non-destructively discover a stdio server by passing its command as a JSON array. Discovery sends initialization and `tools/list` only; it never invokes a tool:

```powershell
verify mcp-scan --stdio-command '["npx","-y","@modelcontextprotocol/server-everything"]'
```

Run untrusted server binaries in a disposable container or VM. See `docs/PHASE5.md` and `SECURITY.md` for limitations and responsible disclosure.

## Runtime agent security gateway

Evaluate an action against a versioned policy:

```powershell
verify gateway check --policy examples/gateway-policy.json --request examples/gateway-request.json
```

Set `REPLAYGUARD_APPROVAL_SECRET` to the same high-entropy value for every gateway process that issues or consumes approval tokens. Use `verify gateway approve`, `revoke`, and `audit` for human approvals, emergency revocation, and decision-chain verification. See `docs/PHASE6.md` before production use.

## RAG reliability and provenance (Phase 7)

Evaluate retrieval, citations, source freshness and authority, tenant isolation, permissions, poisoned documents, and complete answer provenance locally:

```powershell
verify rag evaluate --suite examples/rag-suite.json --output .verify/rag-report.json
verify rag aibom --manifest examples/aibom-manifest.json --output .verify/aibom.json
verify rag compare .verify/rag-report-v1.json .verify/rag-report-v2.json
```

The bundled benchmark uses 100 real, manually annotated RAGTruth test responses pinned to an upstream commit. Refresh it with `python tools/fetch_ragtruth.py` and reproduce the gates with `python tools/benchmark_rag.py`. See `docs/PHASE7.md` for measured results, limitations, and the remaining external adoption gates.

## Cost per verified success (Phase 8)

Analyze attributed model usage against a versioned price catalog, enforce a CI budget, and request a quality-constrained recommendation:

```powershell
verify cost analyze --records tests/data/cost-preference-records.json --catalog examples/price-catalog-2025-06.json --output .verify/cost-report.json --max-total 1
verify cost recommend --report .verify/cost-report.json --baseline candidate-1 --min-quality 0.45
verify cost reconcile --records provider-billing-records.json --catalog price-catalog.json --tolerance 0.05
```

Run `python tools/benchmark_cost.py` to reproduce the real OpenAI human-preference experiment. Price catalogs are immutable snapshots; verify current provider rates before production use. See `docs/PHASE8.md` for results and limitations.

## General-availability operations (Phase 9)

The hosted API contract is stable at v1.0.0 and includes migrations, request quotas, opt-in metadata-only analytics, liveness/readiness checks, workspace SLO reports, backup manifests, verified restore copies, and release attestations.

```powershell
verify ga backup --database .verify/hosted.sqlite3 --output D:\replayguard-backups\daily.sqlite3
verify ga restore-copy --backup D:\replayguard-backups\daily.sqlite3 --output .verify/recovery-test.sqlite3
verify ga readiness --database .verify/recovery-test.sqlite3
```

Review `docs/PHASE9.md`, `docs/API_VERSIONING.md`, `docs/INCIDENT_RESPONSE.md`, `docs/BACKUP_RECOVERY.md`, `docs/SELF_HOSTING.md`, and `docs/DATA_PROCESSING.md` before handling production data.

## Commands

- `verify init`: initialize `.verify/` with private-content defaults.
- `verify record SCRIPT [--capture-content]`: execute and record an instrumented Python script.
- `verify replay RUN_ID`: exact, fixture-only replay.
- `verify compare LEFT RIGHT`: structural/content-identity/efficiency comparison.
- `verify test RUN_ID ASSERTION [VALUE]`: deterministic assertions.
- `verify inspect [RUN_ID]`: list or inspect local runs.
- `verify redact-check [FILE]`: fail if seeded secret patterns remain.
- `verify prune --keep N`: enforce index retention.

## Phase 1 scope and status

Implemented: CLI, Python SDK, versioned language-neutral JSON schema, SQLite metadata, content-addressed payloads, opt-in content capture, redaction, exact/selective/comparative replay primitives, deterministic and explicitly probabilistic assertions, local comparison reports, retention control, and a 50-case corpus.

Not honestly claimable from code alone: five design-partner installations, three replays of real failures, two measured debugging-time reductions, cross-language TypeScript implementation, and benchmark gates on representative production workloads. These remain validation gates, not completed engineering tasks. See `docs/PHASE1.md`.
