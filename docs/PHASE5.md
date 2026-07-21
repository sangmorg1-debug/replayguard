# Phase 5 MCP scanner completion record

## Implemented

- Static scanning of MCP `tools/list` manifests.
- Non-destructive stdio discovery limited to `initialize`, `notifications/initialized`, and `tools/list`.
- JSON-RPC version, response-ID, result/error, and structured-error validation.
- Tool name uniqueness and validity checks.
- Strict JSON Schema and undeclared-argument checks.
- Tool-description and recorded-output poisoning detection.
- Annotation contradiction and consequential-action confirmation checks.
- Path confinement, network allowlist/SSRF, raw execution, and credential-field checks.
- Stable rule IDs, severities, evidence, preconditions, impact, reproduction, remediation, and categories.
- Deterministic JSON and Markdown reports with SHA-256 report identity.
- Rule/tool-specific suppression file support.
- Configurable CI threshold through `--fail-on`.
- Twelve safe threat scenarios covering injection, poisoning, hijacking, exfiltration, traversal, argument injection, credentials, agency, memory, confused deputy, retry denial, and code execution.

## Safety properties

- Discovery never sends `tools/call`.
- Recorded server outputs are parsed only as data and never executed.
- The stdio process receives a reduced environment and temporary working directory.
- Startup failure, missing `tools/list`, invalid responses, and timeouts cannot become successful zero-tool scans.
- Active stdio scanning still executes a user-supplied server binary and is **not an OS sandbox**. Use a disposable container or VM for untrusted servers. Static manifest scanning is safest.

## Automated evidence

- All 13 seeded rule classes are detected in the controlled vulnerable manifest.
- Strict benign manifest produces zero findings.
- Suppressions, protocol failures, startup failure, deterministic hashing, Markdown output, and CI exit codes are tested.
- Scanner module coverage is 95%, with all security rules and failure paths covered.
- Official `@modelcontextprotocol/server-everything` discovery succeeded: 13 tools, every protocol check passed, no high/critical findings. The scanner reported 13 medium schema-hardening notices because those tool schemas do not explicitly reject additional properties; these are recommendations, not claims of exploitable vulnerabilities.

## External gates pending

Coverage across 25 external MCP projects, 80% adapter-free compatibility, maintainer acknowledgements, five CI adoptions, independent security review, and responsible disclosure outcomes require broader external execution and coordination. Do not report findings against third-party projects without manual confirmation and the process in `SECURITY.md`.
