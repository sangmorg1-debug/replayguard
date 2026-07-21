# Phase 3 completion record

## Implemented

- Composite GitHub Action in `action.yml`.
- Fork-safe `pull_request` workflow with `contents: read`, no secret references, and checkout credentials disabled.
- Local smoke workflow compatible with `act` when Docker and `act` are installed.
- Deterministic required-check exit status.
- Baseline/candidate comparison through a language-neutral candidate map.
- Changed-case selection using `path:` tags or `source_files` trace attributes.
- Markdown job summary ordered around merge safety, failures, behavior changes, tools/security, probabilistic evidence, and reproduction.
- Machine-readable JSON results.
- Hash-addressed evidence bundle with commit, schema/suite versions, evaluator versions, model/prompt identifiers, fixture hashes, results/report hashes, timestamp, and environment.
- Report redaction before persistence or publication.
- Evidence artifact upload with 14-day retention.

## Security posture

- The workflow does not use `pull_request_target`.
- It does not reference secrets or request write permissions.
- Untrusted PR code runs only with read-only repository permission.
- Checkout does not persist credentials.
- Raw trace content is not embedded into the Markdown report or evidence metadata.
- A separate privileged PR-comment workflow was deliberately omitted; GitHub's native job summary and check status provide the report without crossing trust boundaries.

## Automated evidence

- Passing merge gate emits `SAFE TO MERGE`, JSON results, and a hash-addressed bundle.
- Seeded changed answer, cost increase, extra tool, and prohibited tool produce a nonzero exit and `BLOCKED` report.
- Changed-path filtering and unscoped fallback cases are tested.
- Reports are tested against a seeded secret.
- CI/reporting module has 100% test coverage.
- Full project suite: 99 passed, one opt-in network test skipped, 93% total coverage.

## External gates pending

GitHub-hosted execution, ten repository installations, weekly retention, required-check adoption, usability timing, and real regressions caught before merge require actual external repositories and users. `act` and Docker were not installed on the development machine, so local workflow-container execution remains a user-environment check; the underlying Action command and all pass/fail behavior are tested directly.

