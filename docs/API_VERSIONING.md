# Public API and schema policy

ReplayGuard's hosted API is stable at version 1.0.0. Paths under `/v1` remain backward compatible for the lifetime of major version 1. `schemas/public-api-v1.contract.json` is the executable minimum contract.

- Removing an operation, changing its HTTP method, making an optional request field required, or removing a response field requires a new major version.
- Additive optional fields and endpoints are minor changes. Documentation-only corrections are patches.
- Deprecated operations remain available for at least one minor release and six months. Responses will carry `Deprecation` and `Sunset` headers before removal.
- Trace, suite, RAG, AIBOM, cost, policy, and price-catalog schemas version independently. Readers must reject unsupported major versions and preserve unknown additive fields where practical.
- Database changes are forward-only migrations recorded in `schema_migrations`. Rollback means restoring the tested pre-migration backup, not attempting lossy down-migrations.
- Run `verify ga readiness --database <path>` before release. A missing v1 operation fails readiness.
