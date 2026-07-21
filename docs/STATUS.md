# Service status and SLO

Public deployments should publish a status page separate from the application origin. It must show API, ingestion, report generation, and authentication status plus incident history.

The application exposes:

- `/livez` for process liveness.
- `/readyz` for database integrity and migration readiness.
- `/health` for backward-compatible health information.
- `/v1/slo` for authenticated workspace availability and p95 latency measurements.

Initial readiness target: 99.9% successful non-5xx responses and p95 API latency under one second. A local or short synthetic run is not evidence that the availability target has been achieved.
