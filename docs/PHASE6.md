# Phase 6 runtime agent security gateway completion record

## Implemented

- Deterministic, versioned JSON policy sets with activation and rollback.
- Authorization context for user, agent, tool, action, arguments, classification, environment, task, user intent, history, risk, location, cost, retries, recursion, idempotency, and untrusted annotations.
- Outcomes: allow, deny, require confirmation, rewrite arguments, sandbox, rate limit, and escalate.
- Approved filesystem roots, network domains, recipients named in user intent, transaction caps, cost limits, retry limits, recursion limits, and per-agent/tool rates.
- Secret-to-open-world denial and unsafe-shell denial.
- One-time, request-bound, expiring human approval tokens with replay prevention.
- Emergency user, agent, and tool revocation.
- Callable gateway that never invokes denied actions and uses a separate adapter for sandbox decisions.
- Complete human-readable decision explanations.
- Redacted, hash-chained SQLite audit log and deterministic decision replay by request digest.
- Fail-closed behavior on policy or audit failure.
- CLI for checks, approvals, revocations, and audit verification.

## Automated evidence

- Controlled benchmark blocks 100/100 malicious actions and permits 100/100 legitimate read actions.
- Unsafe shell, traversal, SSRF/private destinations, recipient substitution, transaction overflow, and secret exfiltration are independently tested.
- One-time approval replay is rejected.
- Tampering invalidates the audit chain.
- Denied secrets are absent from decision output and the SQLite file.
- Policy save, activation, and rollback are tested.
- Gateway module coverage: 96%.
- Full project suite: 124 passed, one opt-in network test skipped; 94% total coverage.

Run `python tools/benchmark_gateway.py` for current machine results. The test gate requires p95 policy latency below 100 ms.

## Operational limitations and external gates

This is an in-process/CLI gateway foundation, not a hardened network appliance. Production deployment still requires authenticated network transport, durable distributed rate limiting, managed key storage, high-availability failover, clock controls, centralized approval UI, an actual sandbox implementation, load testing, and penetration testing.

**Concurrency is untested.** The test suite exercises the gateway single-threaded; approval-token consumption and audit-chain writes have not been verified safe under concurrent requests from multiple agent processes or threads. Treat the gateway as experimental under concurrent load until this is hardened and tested — do not rely on it as the sole control for approval-replay prevention in a multi-process deployment.

Five staging teams, three production workloads, one paying security customer, and independent penetration testing require external deployments and cannot be satisfied by local automation.

