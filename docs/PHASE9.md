# Phase 9 general-availability completion record

Phase 9 engineering readiness is complete. ReplayGuard is not honestly market-validated GA until the adoption, retention, availability-window, and security gates below are demonstrated in production.

## Implemented

- Stable FastAPI v1.0.0 surface and executable `public-api-v1` compatibility contract.
- `ReplayGuard-API-Version` response header and documented semantic version/deprecation policy.
- Idempotent database migration ledger and readiness check for expected migration version.
- Separate liveness, readiness, and backward-compatible health endpoints.
- Per-workspace monthly request limits and usage reporting.
- Workspace availability and p95 latency calculation against explicit 99.9%/one-second targets.
- Privacy-controlled analytics disabled by default and restricted to an allowlist of metadata fields.
- SQLite online backups with SHA-256 manifests and non-overwriting restore-copy integrity verification.
- Release workflow that tests, builds, uploads, and creates GitHub build-provenance attestations.
- Incident response, support, API versioning, backup/recovery, data-processing, status/SLO, self-hosting, security disclosure, and roadmap-boundary documents.
- Complete customer export remains available through `/v1/export`; retention and workspace deletion remain tested Phase 4 capabilities.

## Reproduce readiness

```powershell
python tools/ga_readiness_drill.py
python -m pytest tests/test_phase9.py -q
verify ga readiness --database .verify/hosted.sqlite3
```

The disposable drill performs migrations, writes 1,000 attributed requests, calculates the SLO, creates an online backup, restores a separate copy, validates SQLite integrity, and checks every stable v1 operation against the live OpenAPI document.

## Engineering gates achieved

- Public operation removals fail the compatibility test.
- Migrations are idempotent and recorded.
- Backup restoration preserves evidence and passes full database integrity checking.
- Unknown or exhausted workspace usage returns HTTP 429 rather than silently exceeding configured limits.
- Analytics records nothing before explicit owner opt-in and never stores arbitrary supplied properties.
- Readiness requires database integrity, current migration version, and complete v1 API compatibility.
- Release configuration produces test-gated provenance attestations.
- Documentation covers upgrades, incidents, support, data processing, recovery, status reporting, and self-hosting limitations.

## External GA gates not claimable from code

- 25 weekly active teams, 10 paying teams, and five customers retained for three months.
- Monthly customer churn below 5% for the initial cohort.
- 30% eight-week weekly CI retention among activated repositories.
- Measured hosted p95 availability of 99.9% over the readiness period. The measurement mechanism exists; the production observation window does not.
- Independent confirmation of zero unresolved critical vulnerabilities.
- Timed off-host restoration within the production recovery objective.
- 80% unaided activation in documentation usability testing.
- Hosted gross margin above 70% and sustainable measured support demand.
- Evidence that one use case accounts for a majority of retained usage.

Until these gates pass, describe the software as technically GA-ready or a release candidate—not as a proven generally available commercial service.

## Known limitation

The hosted reference deployment remains single-node SQLite. It is suitable for controlled deployments but is not a multi-region high-availability architecture. The included SLO machinery measures behavior; it does not create redundancy.
