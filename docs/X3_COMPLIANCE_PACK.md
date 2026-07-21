# X3 EU AI Act evidence pack

Generate a local evidence pack with:

```console
verify compliance-pack --workspace . --output .verify/compliance-pack --profile all
```

Profiles are `gpai`, `provider`, `deployer`, and `all`. The command discovers recognized
ReplayGuard artifacts under `.verify`, copies them into a self-contained `evidence` directory,
records their source paths, sizes, and SHA-256 hashes, and writes `pack.json` plus `coverage.md`.

The coverage table uses four deliberately different states:

- `evidence`: the pack contains relevant technical evidence.
- `partial`: artifacts can support the obligation but cannot complete it.
- `missing-evidence`: an automatable evidence category has no artifact in this workspace.
- `process`: the obligation requires accountable organizational, legal, disclosure, or reporting work.

The sources are Regulation (EU) 2024/1689 (`CELEX:32024R1689`), the GPAI Code of Practice and
Model Documentation Form published 10 July 2025, and the Commission Article 50 Guidelines
published 20 July 2026. Article 50 applies from 2 August 2026. The pack does not decide whether
an organization or product is in scope and is not legal advice, a conformity assessment, or a
compliance certification.

Packaged evidence can contain sensitive trace or audit information. Keep the output local,
apply appropriate access controls, and review every artifact before disclosing it.
