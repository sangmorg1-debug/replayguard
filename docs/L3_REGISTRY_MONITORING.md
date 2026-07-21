# L3 MCP Registry monitoring

Initialize from an existing full ReplayGuard registry snapshot:

```console
verify mcp-monitor \
  --history .verify/mcp-registry-monitor \
  --seed-snapshot .verify/mcp-registry-2026-07-19/snapshot.json \
  --fail-on none
```

Run the next full sweep and fail automation when a confirmed severity threshold is reached:

```console
verify mcp-monitor --history .verify/mcp-registry-monitor --fail-on high
```

For a local long-running schedule, add `--interval-seconds 86400`. Intervals below 60 seconds
are rejected. Each cycle writes a complete source snapshot, JSON and Markdown diff reports, and
an atomic-style `latest.json` pointer. The official API retains every immutable version, but
comparison uses only records marked `isLatest`; this avoids treating version history as current
capability surface.

Escalation alerts cover:

- new remote destinations and transport headers;
- new package/install surfaces;
- new runtime or package command arguments;
- new required, secret, or filepath configuration inputs;
- repository provenance and registry status changes;
- scanner rules newly triggered by the latest manifest.

The monitor is static-only. It never installs packages, connects to declared remote servers, or
invokes MCP tools. Alerts include server names for local operational review, but they are not
verified vulnerabilities and must not be disclosed or used for enforcement without manual
confirmation and the responsible-disclosure process in `SECURITY.md`.

The real initial baseline contains 55,159 version records and 17,665 latest server identities.
Its API response SHA-256 is
`5b59475aab725412fb70b5388a559a309c7e21da7c6735d427cb17e3a89cc2ff`.
