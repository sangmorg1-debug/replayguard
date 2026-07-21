# Data processing summary

ReplayGuard stores tenant metadata needed for traces, reports, suites, baselines, datasets, audit records, usage limits, and service health. Trace and report contents are opt-in; suite and dataset contents require encryption. Customer content is redacted before encryption and is never used for model training.

Usage accounting stores workspace ID, endpoint template/path, status code, latency, request byte count, and timestamp. Product analytics are disabled by default. When enabled, only allowlisted endpoint, status, and API-version metadata is recorded; request and response content is excluded.

Workspace owners control retention, export, analytics consent, and deletion. Deployment operators must document hosting region, subprocessors, legal basis, backup retention, security contact, and deletion behavior for their environment before accepting production customer data.
