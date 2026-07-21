# N4 MCP Registry static sweep

`verify mcp-scan --registry` follows the official frozen `/v0.1/servers` cursor API through
exhaustion and writes three local artifacts:

- `snapshot.json`: every registry response record plus endpoint, retrieval time, cursors, and a
  SHA-256 over the canonical page responses.
- `report.json`: aggregate-only machine-readable results with its own deterministic digest.
- `report.md`: a publication-safe aggregate summary.

```powershell
verify mcp-scan --registry --output .verify/mcp-registry --fail-on critical
```

The sweep is deliberately static. It does not install packages, connect to declared remote MCP
servers, request `tools/list`, or invoke tools. Registry records contain distribution manifests,
not tool schemas, so this work cannot claim tool-level or runtime security coverage.

## Live real-data gate

Full sweep completed 2026-07-19 Pacific time against
`https://registry.modelcontextprotocol.io/v0.1/servers`:

| Measure | Result |
|---|---:|
| API pages | 552 |
| Versioned manifest records | 55,159 |
| Unique servers | 17,665 |
| Active records | 54,657 |
| Deprecated records | 502 |
| Unpinned package references (`RGM004`) | 7,243 |
| Potential embedded sensitive environment values (`RGM005`) | 0 |

Two initial sensitive-name candidates were manually checked without exposing their values. Both
were the same five-character, low-entropy benign configuration literal repeated across versions;
the calibrated rule excludes documented boolean/null/test defaults. Future candidate identities
and evidence remain excluded from aggregate reports and require the responsible disclosure workflow
in `SECURITY.md`. An unpinned package is a supply-chain hardening concern, not proof of exploitation.

The registry changed by three version records between two sweeps minutes apart, while the unique
server count and unpinned-package count remained stable. The retained calibrated snapshot is therefore
identified by retrieval time `2026-07-20T05:34:45.887831+00:00` and SHA-256
`5b59475aab725412fb70b5388a559a309c7e21da7c6735d427cb17e3a89cc2ff`; counts are not timeless.

The pagination contract has automated coverage for URL-encoded cursors, termination, repeated
cursor rejection, partial-preview limits, immutable snapshot hashing, source mutual exclusion,
and the no-execution boundary. Registry response data remains under ignored `.verify/` storage
rather than being redistributed in the repository.
