# X4 TypeScript SDK and conformance

The SDK is in `sdk/typescript` and emits the same ReplayGuard trace schema `1.0.0` as Python.
It provides `Recorder`, `validateTrace`, and a fixture-only `exactReplay` function with no live
call path.

```console
cd sdk/typescript
npm ci
npm test
```

The cross-language pytest gate uses the existing checksum-pinned public corpus:

- 25 Berkeley Function Calling Leaderboard v4 cases are recorded by TypeScript, validated
  against `schemas/trace-v1.schema.json`, and exactly replayed by Python.
- A Python-produced BFCL trace and the real tau2-bench voice simulation
  `49b22f0c-4a56-41c5-922f-bc2a56e53a23` (972 ticks) are validated and exactly replayed by
  TypeScript.

Every replay asserts zero live calls and stable event kind, name, request, response, attributes,
usage, and status. IDs and timestamps intentionally change to identify the replay operation.
The published SDK has no runtime dependencies; TypeScript and Node type packages are exact-pinned
development dependencies in `package-lock.json`.
