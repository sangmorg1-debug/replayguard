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
- Redacted, hash-chained SQLite audit log and deterministic decision replay by request digest, safe under concurrent writers (atomic approval consumption, `BEGIN IMMEDIATE` chain writes).
- Fail-closed behavior on policy or audit failure.
- CLI for checks, approvals, revocations, and audit verification.

## Automated evidence

- Controlled benchmark blocks 100/100 malicious actions and permits 100/100 legitimate read actions.
- Unsafe shell, traversal, SSRF/private destinations, recipient substitution, transaction overflow, and secret exfiltration are independently tested.
- One-time approval replay is rejected.
- Tampering invalidates the audit chain.
- Denied secrets are absent from decision output and the SQLite file.
- Policy save, activation, and rollback are tested.
- Approval consumption and audit-log writes are race-tested under 16 concurrent threads.
- Gateway module coverage: 96%.
- Full project suite: 124 passed, one opt-in network test skipped; 94% total coverage.

Run `python tools/benchmark_gateway.py` for current machine results. The test gate requires p95 policy latency below 100 ms.

## Operational limitations and external gates

This is an in-process/CLI gateway foundation, not a hardened network appliance. Production deployment still requires authenticated network transport, durable distributed rate limiting, managed key storage, high-availability failover, clock controls, centralized approval UI, an actual sandbox implementation, load testing, and penetration testing.

**Concurrency:** approval consumption is a single atomic `UPDATE ... WHERE used_at IS NULL`, and audit-log writes use `BEGIN IMMEDIATE` to close the read-then-write window between reading the chain's tail hash and inserting the next entry. Both are tested under 16 concurrent threads (`test_concurrent_approval_consumption_only_succeeds_once`, `test_concurrent_decisions_keep_the_audit_chain_valid` in `tests/test_phase6.py`) hitting a shared SQLite file. The locking mechanism (SQLite's RESERVED lock via `BEGIN IMMEDIATE`, atomic single-statement `UPDATE`) is file-level and applies the same way across separate processes as across threads, but that specific path — separate OS processes contending for the same database file — has not been exercised by a test, only by threads within one process. A networked/replicated database has not been tested at all; that's a different mechanism multi-host deployment would require.

Five staging teams, three production workloads, one paying security customer, and independent penetration testing require external deployments and cannot be satisfied by local automation.

