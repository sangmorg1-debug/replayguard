# Security and responsible disclosure

Report suspected ReplayGuard vulnerabilities privately to the project owner before public discussion. Do not include real credentials, customer traces, or exploitable third-party details in public issues.

For scanner findings in another MCP project:

1. Reproduce the result deterministically against a pinned version.
2. Manually confirm impact and eliminate false positives.
3. Do not invoke destructive tools or access data without explicit authorization.
4. Use the maintainer's published security contact or private advisory process.
5. Provide the affected tool, prerequisites, minimal reproduction, evidence, impact, and remediation.
6. Allow a reasonable remediation period before coordinated disclosure.
7. Treat medium hardening notices as recommendations unless exploitability is demonstrated.

The scanner is a testing aid, not proof that a server is safe or vulnerable.

For ReplayGuard itself, use GitHub private vulnerability reporting when available or the repository owner's published private security contact. Include affected versions, prerequisites, impact, and a minimal non-destructive reproduction. Expect acknowledgement within three business days. Do not test against customer systems or access data without authorization. Good-faith research following these rules will be coordinated privately; disclosure timing depends on impact and remediation readiness.

Release-tag builds run the complete test suite and use GitHub artifact attestations to issue build provenance for distributions. Consumers must verify the attestation and package digest before deployment.
