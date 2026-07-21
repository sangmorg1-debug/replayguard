# Self-hosting decision

ReplayGuard supports local-only CLI use and a single-node self-hosted FastAPI/SQLite deployment. The source distribution includes export, retention, deletion, backup, restoration, readiness, and migration mechanisms, so customers are not locked into the hosted service.

The current self-hosted profile is appropriate for development, evaluation, and controlled small-team deployments. Operators own TLS termination, process supervision, off-host encrypted backups, master-key custody and rotation, monitoring, upgrades, regional requirements, and high availability.

The project does not currently claim turnkey multi-node clustering, zero-downtime database migration, managed KMS integration, enterprise identity federation, or a self-hosted 99.9% SLA. Those require evidence from production deployments before becoming roadmap commitments.
