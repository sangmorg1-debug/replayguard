# Private-beta privacy model

- Trace and report bodies are not captured unless `capture_content` is explicitly true.
- Metadata includes identifiers, names, timestamps, event counts, status, latency, cost, repository, commit, and pass state.
- Known secrets are redacted before encrypted content persistence.
- Explicit content is encrypted at rest using a key derived separately for each workspace from the deployment master key.
- API keys are displayed once and stored only as hashes.
- ReplayGuard does not use customer data for training.
- The self-hosted build has no telemetry or subprocessors and sends no customer data externally.
- Retention is workspace-configurable from 1 to 3,650 days.
- Tenant exports are available through `/v1/export`.
- Trace deletion is immediate in the active database. Workspace deletion transactionally removes all active tenant records.
- Operators remain responsible for removing deleted data from backups according to their documented backup-expiration interval.
- Metadata is not application-layer encrypted in the SQLite beta. Protect the database and host filesystem, and use full-volume encryption.

