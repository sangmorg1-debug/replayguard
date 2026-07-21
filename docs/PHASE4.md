# Phase 4 private-beta completion record

## Implemented capabilities

- Self-hostable FastAPI service and `verify serve` command.
- Team workspaces represented by tenant-bound API keys with owner, editor, and viewer roles.
- Trace history with metadata-first capture and encrypted opt-in content.
- Shared regression suites, datasets, and baselines.
- Retained CI reports and tenant-authenticated report retrieval.
- Daily report trends and aggregate cost, latency, pass, trace, and report summaries.
- Configurable retention enforcement.
- Immediate trace deletion and transactional workspace offboarding.
- Complete JSON export, including tenant content that was explicitly stored.
- Tenant-scoped audit trail for consequential mutations.
- Request size limits and no-store/nosniff response headers.

## Security and privacy evidence

- API keys contain 256 bits of randomness and only SHA-256 hashes are persisted.
- Tenant identity is derived from the authenticated key; caller-provided tenant IDs are not accepted.
- Every object lookup and mutation is constrained by the authenticated workspace ID.
- Cross-tenant direct reads, lists, exports, report retrieval, and deletes are tested.
- Unknown cross-tenant IDs return the same 404 result as missing IDs.
- Content capture defaults off and is rejected if encryption is not configured.
- Opt-in content is redacted and encrypted with a workspace-derived Fernet key before SQLite persistence.
- Seeded plaintext content and raw API keys are verified absent from the database file.
- Workspace deletion removes workspace, keys, traces, suites, datasets, baselines, reports, and audit records.

## Run locally

Set a long random master key in the environment, then start bootstrap mode only for initial local setup:

```powershell
$env:REPLAYGUARD_MASTER_KEY = python -c "import secrets; print(secrets.token_urlsafe(48))"
verify serve --allow-bootstrap --host 127.0.0.1 --port 8787
```

Create the first workspace with `POST /v1/bootstrap`, save the returned API key, then restart without `--allow-bootstrap`. Interactive API documentation is available at `http://127.0.0.1:8787/docs`.

## Automated results

- Seven Phase 4 API/security scenarios pass.
- Full project suite: 106 passed, one opt-in network verification skipped.
- Total coverage: 94%; hosted persistence: 98%; API routes: 99%.

## External beta gates pending

Twenty invited teams, ten activations, four-week retention, production-bound PR use, paid commitments, onboarding time, support load, hosted gross-margin estimates, and real infrastructure penetration testing require an actual deployed beta and external users. This implementation is self-hostable beta software, not a claim that those market gates have passed.

Before public internet exposure, add a production database with row-level security, TLS termination, managed secret storage, backups, monitoring, per-tenant rate limiting, API-key rotation/revocation UI, and an independent security review.

