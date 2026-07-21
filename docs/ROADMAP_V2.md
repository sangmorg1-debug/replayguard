# ReplayGuard Roadmap v2 (2026-07 onward, restructured 2026-07-21)

Phases 1–9 and every N/X/L engineering item below are engineering-complete or explicitly marked
otherwise. **The roadmap's #1 committed priority is no longer more building — it is L5 external
validation**, promoted here from the bottom of the old "Later" list to the top. No engineering item
on this roadmap substitutes for it; see `ROADMAP_BOUNDARIES.md`: "roadmap order is driven by
retained weekly use and prevented harmful changes, not demonstration breadth." This restructuring
is the first roadmap revision to actually follow that ordering rather than stating it.

Evidence reviewed: 2026-07-19 (original roadmap), rechecked 2026-07-21 for this restructuring.
Time-sensitive standards, APIs, acquisition status, and legal timelines must be rechecked from the
cited primary source when work starts.

Constraints inherited from `ROADMAP_BOUNDARIES.md`: local-first, deterministic gates first,
no observability-dashboard sprawl without validated demand.

---

## The lead wedge

**Replay + failure diagnosis on existing OTel traces.** Point ReplayGuard at your
Langfuse/Arize/Datadog OpenTelemetry traces, replay them offline with no live side effects, and get
ranked failure suspects — no re-instrumentation required. This is enabled by N1 (the OTel bridge,
complete) and N2/`verify diagnose` (complete, with an opt-in experimental claim-graph signal).
Everything else in this document — the security scanner, the gateway, RAG provenance, cost
analysis, the compliance pack, the TypeScript SDK — is supporting surface around this one wedge, not
a second product. `docs/QUICKSTART_DIAGNOSE.md` walks through it end to end with a public,
non-gated sample trace.

---

## NOW — the one committed priority

### L5. Independent security review + design-partner validation (Track: Validation) — **top priority**

The still-open human gates from Phases 1–9. Nobody outside this workspace has ever run ReplayGuard;
no real GitHub PR has ever exercised the Action; no design partner has ever used it on a real
failure. No engineering item on this roadmap substitutes for these gates, and none of them can be
satisfied by more building, more benchmarks, or self-attestation.

**Status, 2026-07-21:** execution protocol complete, all gates open. `docs/L5_EXTERNAL_VALIDATION.md`
defines reviewer independence and scope for an independent security review (Track A) and the
five-partner, three-confirmed-replay, two-measured-time-reduction protocol for design-partner
validation (Track B). Current ledger:

| Gate | Required evidence | Status |
|---|---|---|
| Independent security review | Signed scoped report and retest | Open |
| No unresolved critical/high findings | Private finding ledger | Open |
| Five partner installations | Five consented study records | Open |
| Three real-failure replays | Checksummed evidence + partner confirmation | Open |
| Two measured time reductions | Raw paired/crossover durations | Open |
| Four-week retained use | Follow-up records | Open |

**What actually moves this forward:** shipping v1.0.0 to a real public repository, running the
real-PR demo described in `docs/PHASE3.md` and `docs/RELEASE_CHECKLIST.md`, and then finding 1–3
real users — not another benchmark pass. See "R&D findings (parked)" below for why continued TRAIL
research has hit diminishing returns and should not be the next move.

---

## Supporting engineering surface (all complete unless noted)

The items below make the lead wedge and its surrounding surface possible. They are engineering-complete
and are not the current bottleneck — L5 is. Status lines are unchanged in substance from the
2026-07-19/20 roadmap; the long research narrative previously inlined under N2 has moved to
`docs/RESEARCH_TRAIL_DIAGNOSIS.md` (see appendix) to keep this document focused on what ships.

### N1. OTel GenAI trace bridge (Track: Interop) — enables the lead wedge
Import OTLP/JSON spans (GenAI + MCP semantic conventions, plus OpenInference attributes) into the
canonical ReplayGuard trace schema; export ReplayGuard runs as OTLP.

**Status: complete.** Ten pinned public OpenInference spans and all 148 TRAIL trace files pass
normalized round-trip; both the public repository and the authorized Hugging Face revision measure
4,626 recursively expanded spans (117 GAIA / 31 SWE-Bench), every file checksum verified, zero
semantic mismatches. See `N1_OTEL_BRIDGE.md`.

### N2. Failure localization engine (`verify diagnose`) — enables the lead wedge
Ranks suspect spans in a failing trace using deterministic comparators, scorable against TRAIL's
human annotations.

**Status: baseline complete; research parked.** Official macro joint accuracy on all 148 TRAIL
traces is 17.84% (95% CI 13.79%–22.14%), pair precision 10.24%, F1 10.55%; a held-out hardening
pass reaches 17.75% precision / 8.29% recall / 11.30% F1 on 127 untouched traces. This is the
production deterministic baseline and remains the CLI default. An opt-in
`--experimental-claim-graph` flag (new, 2026-07-21) adds the one research layer that generalized —
see `docs/DIAGNOSE_CLAIM_GRAPH.md`. Nine further stacked layers, a tiny local model, and
cross-dataset generalization testing were completed and are now parked as research findings, not
further engineering work — see the appendix. Full detail: `N2_FAILURE_LOCALIZATION.md`,
`docs/RESEARCH_TRAIL_DIAGNOSIS.md`.

### N3. pytest plugin + CI ergonomics (Track: Adoption)
**Status: complete.** `pytest-replayguard` auto-discovers; record, exact replay, isolated-store, and
suite-case fixtures ship. Dogfood collects all 106 real public regression cases; a scripted timing
gate enforces install-to-passing-replay under 10 minutes. See `N3_PYTEST_PLUGIN.md`.

### N4. MCP Registry sweep (Track: Security + distribution)
**Status: complete.** Static sweep run to cursor exhaustion against frozen `/v0.1`: 552 pages,
55,159 versioned manifests, 17,665 unique servers, 7,243 unpinned package references found. No
package or server executed or contacted. See `N4_MCP_REGISTRY_SWEEP.md`.

### X1. Semantic hallucination judge (Track: RAG)
**Status: complete, gate passed.** Untouched 2,128-record RAGTruth holdout reaches 80.24% precision
/ 70.71% recall at threshold 0.63, clearing the ≥80%/≥70% target. Advisory unless
`--semantic-gate` is explicitly supplied. Cross-domain (LLM-AggreFact/FaithBench) validation
remains open — those sources require accepted access conditions not yet obtained. See
`X1_SEMANTIC_JUDGE.md`.

### X2. ATLAS/OWASP threat mapping (Track: Security)
**Status: complete.** Every scanner rule and gateway policy category carries ≥1 ATLAS/OWASP
mapping; `verify threat-map` publishes JSON/Markdown coverage matrices and lists uncovered
agent-relevant ATLAS techniques. See `X2_THREAT_MAPPING.md`.

### X3. EU AI Act evidence pack (Track: Compliance)
**Status: complete.** `verify compliance-pack` inventories evidence against Article 50/53/55
obligations, distinguishing direct evidence from non-automatable process obligations. Explicitly
not legal advice or certification. See `X3_COMPLIANCE_PACK.md`.

### X4. TypeScript SDK (Track: Adoption)
**Status: complete.** `@replayguard/sdk` records, validates, and exact-replays schema `1.0.0`
traces in Node.js 20+ and browsers, with a bidirectional Python/TypeScript conformance gate in CI.
See `X4_TYPESCRIPT_SDK.md`.

### L1. Scale ingestion (SWE-bench Verified / tau2 at scale)
**Status: complete.** `verify scale-ingest` streams the official 500-row SWE-bench Verified parquet
and tau2 exports into the content-addressed store; 500 runs / 2,000 events ingested and replayed
fixture-only in under 6 seconds each. See `L1_SCALE_INGESTION.md`.

### L2. Production tap
**Status: engineering-preview complete; design-partner demand validation open.** `verify tap`
implements the OTLP/HTTP JSON ingestion path with sampling, redaction, backpressure, and auth,
tested against real pinned OpenInference spans. It is not production-validated — that requires a
partner actually choosing it for a real workload, which is an L5 Track B outcome, not an
engineering task. See `L2_PRODUCTION_TAP.md`.

### L3. Registry monitoring service
**Status: engineering-complete.** `verify mcp-monitor` persists checksum-addressed snapshots/diffs
and detects server/tool/permission changes on a schedule. See `L3_REGISTRY_MONITORING.md`.

### L4. Multi-agent trace semantics
**Status: blocked, not started by design.** The OpenTelemetry agentic-systems proposal remains an
open Todo and the applicable GenAI semantic conventions remain Development status. ReplayGuard
preserves unknown `gen_ai.*` attributes through N1 but will not freeze draft semantics into its
schema, or claim L4 complete, before the upstream standard matures. Recheck standards status before
resuming.

---

## R&D findings (parked, not abandoned)

Nine stacked diagnosis layers, a tiny local model, cross-dataset transfer testing, a frozen
calibration split, a five-repeat nested cross-validation, and one genuinely external corpus
(RootSE) were completed on top of the N2 baseline. Full methodology, every measured number, and the
competitive-landscape context are consolidated in **`docs/RESEARCH_TRAIL_DIAGNOSIS.md`** — that
document is now the source of truth for this research, superseding the inline narrative that used
to live in this file.

**Bottom line:** the claim/evidence graph is the one layer that generalized (beats baseline on
TRAIL, TELBench, and AgentRx) and now ships as the opt-in `--experimental-claim-graph` flag. The
tiny model, meta-ranker, prefill-attribution pilot, and category-assignment layers are accepted
research findings but do not ship — they either don't generalize (tiny model, meta-ranker LODO), are
not statistically established over the shipped layer (meta-ranker's 1.64 F1 aggregate gain has
confidence intervals crossing zero in every repeat), or aren't reproducible against the published
comparison (the MASPrism-style pilot). The RootSE external zero-shot test confirms the same
conclusion externally: ranking, not candidate discovery, is now the bottleneck, and 148–1,073
benchmark traces across four corpora have been mined about as far as they usefully go.

**Why parked, not continued:** the marginal signal left in these benchmarks is shrinking faster than
the marginal engineering effort required to extract it (RootSE's F1 gain was 0.22 points for a full
new-corpus integration). The project's actual bottleneck is now L5 — real users and a real security
review — not another percentage point on a 148-trace benchmark. Any future work on this research
requires genuinely new labeled traces, not further reuse of TRAIL, TELBench, AgentRx, or RootSE,
all of which are now spent for model selection on at least one axis.

---

## Explicitly not planned
General observability dashboards, autonomous code-fixing, enterprise IAM, and multi-region
hosting remain out per `ROADMAP_BOUNDARIES.md`.

---

## Dependency map

- N1 (OTel bridge) unblocks N2 (TRAIL is OTel-formatted), L2, and L4.
- N1 + N2 together are the lead wedge; everything else is supporting surface.
- N4 (registry sweep) feeds X2 (real findings to map) and L3.
- X1 depends only on Phase 7 interfaces; independent of N-track.
- X4 depends on the frozen v1 trace schema (done, Phase 9).
- L5 depends on nothing engineering-side being unfinished; it depends on actually shipping (see
  `docs/RELEASE_CHECKLIST.md`) and then finding real users and a real reviewer.

## Pinned data sources for this roadmap

| Source | What it provides | License / access |
|---|---|---|
| `PatronusAI/TRAIL` (Hugging Face + GitHub `patronus-ai/trail-benchmark`) | 148 real annotated agent failure traces, OTel spans, 841 labeled errors | MIT; access-gated; acceptance required; redistribution restricted; authorized revision `b424ce63d5973d5dcd7169b1bc3c07ccdee276d1` + local SHA-256 |
| RAGTruth full corpus (`ParticleMedia/RAGTruth`) | ~18k human-annotated RAG responses | MIT, already pinned (subset) |
| LLM-AggreFact / FaithBench | Cross-domain grounding labels for judge validation | Public, pin per dataset; access not yet obtained |
| MCP Registry API (`registry.modelcontextprotocol.io/v0.1`) | Live real server manifests | Public REST; frozen `/v0.1` verified 2026-07-19; snapshot mutable responses |
| MITRE ATLAS v5.x machine-readable release | Tactics/techniques for mapping | Public, pin by version |
| SWE-bench Verified / tau2-bench / BFCL / AgentDojo | Task + trajectory corpus growth | Already pinned in `manifest.json` |
| EU AI Act text + GPAI Code of Practice | Compliance mapping targets | Public, pin by publication date |
| TELBench / AgentRx / RootSE | Cross-dataset diagnosis generalization corpora (research, parked) | Apache-2.0 / MIT / MIT; all pinned; RootSE now spent as an untouched external gate |

All downloads follow the existing rule: pinned revision or retrieval snapshot, SHA-256 in
`tests/data/public/manifest.json`, and refusal of silent drift. Gated datasets are stored only
in an authorized private cache; the public manifest may record metadata and a digest but must
not cause redistribution or bypass access conditions.

## Primary sources reviewed

- [TRAIL dataset card and access conditions](https://huggingface.co/datasets/PatronusAI/TRAIL)
- [TRAIL benchmark repository](https://github.com/patronus-ai/trail-benchmark)
- [OpenTelemetry GenAI semantic conventions repository](https://github.com/open-telemetry/semantic-conventions-genai)
- [Official MCP Registry](https://registry.modelcontextprotocol.io/)
- [RAGTruth corpus](https://github.com/ParticleMedia/RAGTruth)
- [MITRE ATLAS](https://atlas.mitre.org/)
- [European Commission AI Act framework and application timeline](https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai)
- [OpenAI announcement of its agreement to acquire Promptfoo](https://openai.com/index/openai-to-acquire-promptfoo/)
