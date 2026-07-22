# Changelog

## 1.0.0 — 2026-07-21

First tagged release. Phases 1–9 and Roadmap v2 items N1–N4, X1–X4, L1–L3 are engineering-complete;
L4 is explicitly blocked on upstream OpenTelemetry standards maturity; L5 (independent security
review + design-partner validation) is the open external gate this release exists to unblock. See
`docs/ROADMAP_V2.md` for the full status ledger and `docs/L5_EXTERNAL_VALIDATION.md` for what "engineering-complete" does and does not claim.

### Added

- Local-first Python SDK and `verify` CLI: record/replay, deterministic and probabilistic
  comparison, redaction, regression suites, flakiness detection.
- `verify diagnose`: deterministic TRAIL-benchmarked failure localization, plus a new opt-in
  `--experimental-claim-graph` flag adding a training-free, non-gating claim/evidence-graph signal
  (see `docs/DIAGNOSE_CLAIM_GRAPH.md`). Default `verify diagnose` output and exit-code behavior are
  unchanged by this addition.
- `verify otel`: OTel GenAI/MCP/OpenInference trace import/export bridge (N1).
- `pytest-replayguard` plugin for pytest-native record/replay (N3).
- `verify mcp-scan` and `verify mcp-monitor`: static MCP manifest security scanning and registry
  sweep/diff monitoring (N4, L3).
- `verify rag evaluate`: deterministic RAG provenance evaluation plus an optional, revision-pinned
  semantic hallucination judge (`--semantic`), advisory unless `--semantic-gate` (X1).
- `verify threat-map`: MITRE ATLAS / OWASP LLM Top 10 coverage mapping (X2).
- `verify compliance-pack`: EU AI Act evidence assembly, explicitly not legal advice (X3).
- `@replayguard/sdk`: TypeScript SDK with bidirectional Python conformance testing (X4).
- `verify scale-ingest` and `verify tap`: bulk corpus ingestion and an OTLP production-tap
  engineering preview (L1, L2 — L2 is not production-validated).
- Runtime agent security gateway (`verify gateway`) and hosted GA operations
  (`verify ga backup/restore-copy/readiness`).
- Fork-safe composite GitHub Action (`action.yml`) with a required-check-compatible exit status,
  Markdown job summary, and hash-addressed evidence bundle.

### Fixed (pre-release hardening, ahead of the first tag)

An external code review of this codebase found 8 real defects plus 3 items needing either a fix
or an honest scope-down; all 11 are resolved below, each with a regression test that reproduces
the original failure before fixing it.

- Wheel installs (`pip install` from a built package, not `-e`) crashed on `verify rag aibom` and
  `verify ga readiness` — schema files were resolved via a source-tree-relative path that doesn't
  exist in an installed wheel. Bundled as package data, loaded via `importlib.resources`.
- `Recorder.__exit__` stored the top-level exception's raw, unredacted message.
- Async functions passed to `@model_call`/`@tool_call` were never awaited correctly.
- `SuiteRunner` silently reported a case as passing when no candidate run was supplied (a
  false-green CI gate) instead of failing closed on missing evidence.
- `verify otel import` persisted full raw span content by default, bypassing this project's own
  privacy-by-default convention; content capture is now opt-in (`--capture-content`), matching
  `Recorder`.
- `PolicySet` silently ignored unrecognized policy match keys (a typo'd condition would silently
  widen a rule) instead of failing to load.
- `LocalStore.prune()` deleted index rows but left the orphaned blob files on disk.
- The TypeScript SDK's `Recorder.capture()` had no capture-mode gate or redaction at all, an
  asymmetry with the Python privacy-by-default fix above. `RecorderOptions.captureContent` now
  mirrors the Python convention (off by default, known-secret patterns and sensitive keys
  redacted).
- The runtime gateway's approval-token consumption and audit-log writes had real, reproduced
  concurrency races (16 concurrent threads: 4 could consume a one-time approval; the audit hash
  chain could break). Fixed with an atomic `UPDATE ... WHERE used_at IS NULL` and `BEGIN
  IMMEDIATE` audit writes; both verified stable under repeated concurrent runs.
- The 50+-case failure corpus (`tests/test_corpus.py`) built the same generic event for every
  named "family," differing only by which label was attached — not real per-failure-mode
  behavior. Rewritten so each family actually exhibits what its name claims (real raised
  exceptions, real redaction, real `compare_runs` diffs, a real corrupted blob that `load_run`
  must reject, real parent/child linkage).
- "Replay" read like VCR-style code re-execution; exact replay is pure trace reconstruction and
  never re-executes the original code. Clarified in the `Replayer` docstring, README, and
  `docs/N3_PYTEST_PLUGIN.md`.

### Known gaps (stated, not hidden)

- **The GitHub Action has never run in a real GitHub Actions environment before this release.**
  Docker and `act` are not installed in the development environment, so the container-execution
  path was verified only by running the underlying `verify ci` gate directly against the public
  106-case regression suite — once producing a genuine `SAFE TO MERGE` result and once, against a
  deliberately regressed candidate (changed answer, increased cost, an unexpected prohibited tool
  call), a genuine `BLOCKED` result with nonzero exit code. See `.verify/ship-demo/` and
  `docs/RELEASE_CHECKLIST.md` for the real-PR steps that close this gap for good.
- No independent security review has been performed. No design partner has used ReplayGuard on a
  real failure. These are the explicit, open L5 gates — see `docs/L5_EXTERNAL_VALIDATION.md`.
- Cross-domain validation for the semantic RAG judge (LLM-AggreFact/FaithBench) remains open;
  access conditions for those datasets have not yet been obtained.
- Production-tap adoption is implementation-complete but not demand-validated (L2).
- Gateway concurrency fixes above are tested under concurrent threads within one process; the
  same file-level SQLite locking applies across separate OS processes by mechanism but that path
  isn't separately tested, and a networked/replicated database is untested entirely.
