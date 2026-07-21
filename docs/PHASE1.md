# Phase 1 completion record

## Engineering deliverables

| Deliverable | Status | Evidence |
|---|---|---|
| Seven-command CLI | Complete | `src/replayguard/cli.py` |
| Python model/tool instrumentation | Complete | `src/replayguard/recorder.py` |
| Versioned canonical trace model | Complete | `schema.py`, `schemas/trace-v1.schema.json` |
| SQLite + content-addressed storage | Complete | `storage.py` |
| Content-private default and redaction | Complete | `redaction.py`, tests |
| Exact/selective/comparative replay | Complete foundation | `replay.py` |
| Assertion framework | Complete foundation | `assertions.py` |
| 50+ scenario corpus | Complete | `tests/test_corpus.py` |
| Public real-data corpus | Complete | BFCL v4, tau2-bench, and AgentDojo adapters plus pinned fixtures in `tests/data/public` |

## Gate ledger

Automated gates are measured by `pytest`. Product-validation gates are deliberately not inferred from automated tests.

- Quick-start under 15 minutes: ready for timed usability test.
- Corpus recording >=95%: measured in test output.
- Exact structural replay >=98%: measured in test output.
- Zero exact-replay side effects: guarded by architecture and tests.
- Trace overhead <10%: benchmark harness required on agreed representative workloads.
- Seeded-secret detection 100%: measured in tests.
- Public benchmark ingestion and side-effect-free replay: measured across 70+ pinned real records.
- Body capture opt-in: tested.
- Language-neutral schema: JSON Schema complete; TypeScript consumer validation remains.
- Five design partners / three real failures / two debugging-time wins: external validation pending.

## Next validation run

1. Time five fresh developers installing and replaying the quick-start.
2. Run `pytest` on Linux, macOS, and Windows.
3. Benchmark 1,000 no-op model/tool calls with and without capture.
4. Ask five design partners to use the SDK on real applications and record the gate evidence here.
