# L5 independent review and design-partner validation

L5 is ready to execute but is **not complete**. Independent security conclusions and
design-partner outcomes must be produced by people outside the implementation team. Automated
tests, self-review, synthetic users, and public benchmark data cannot satisfy these gates.

## Track A: independent security review

### Reviewer independence and authorization

- Reviewer has had no material role implementing the reviewed controls.
- A written rules-of-engagement document names the exact commit, hosts, test window, contacts,
  allowed techniques, data handling, stop conditions, and disclosure process.
- Testing is limited to infrastructure owned for the review. Customer systems and third-party MCP
  servers are excluded unless their owners separately authorize them in writing.
- Destructive testing, persistence, social engineering, denial of service, and access to real
  secrets or customer traces are excluded by default.

### Minimum scope

1. Trace capture, redaction, encrypted storage, export, and deletion.
2. Hosted API authentication, workspace isolation, authorization, rate limiting, and audit trails.
3. MCP static scanner and active-discovery trust boundary, including process and environment
   isolation limitations.
4. Runtime gateway policy bypass, approval-token replay, revocation, SSRF, traversal, shell and
   argument injection, secret exfiltration, fail-closed behavior, and audit-chain tampering.
5. OTLP production tap authentication, parser limits, redaction, sampling, concurrency,
   backpressure, and malformed payload handling.
6. Python and TypeScript package supply chain, release workflow, dependency review, artifact
   provenance, and installation instructions.

The reviewer receives `SECURITY.md`, `docs/PHASE5.md`, `docs/PHASE6.md`,
`docs/L2_PRODUCTION_TAP.md`, `docs/THREAT_MODEL.md` if added, the source tree, test suite, pinned
public fixtures, and a disposable deployment containing invented credentials only.

### Required deliverables and gate

- Signed report identifying scope, commit SHA, dates, methodology, limitations, and findings.
- Each finding has severity, affected component, prerequisites, evidence, impact, and remediation.
- A retest records fixed, accepted, or unresolved status without deleting the original finding.
- Gate passes only when no critical or high finding remains unresolved and every medium finding has
  a documented owner and disposition. Passing means the reviewed commit passed the agreed scope;
  it is not a claim that ReplayGuard is vulnerability-free.

Store private reports outside the public repository. Record only this non-sensitive ledger entry:

```yaml
review_id: RG-SEC-YYYY-NN
reviewer_organization: ""
reviewer_independent: false
commit_sha: ""
scope_version: l5-v1
started_at: ""
completed_at: ""
report_sha256: ""
critical_open: null
high_open: null
medium_open: null
retest_completed_at: ""
gate: pending
public_summary_url: ""
```

## Track B: design-partner validation

### Cohort and consent

Recruit five distinct teams with real agent applications. At least three should use different
framework or model-provider combinations, and at least two should exercise the MCP gateway or
production tap. A team counts only after a named participant consents to the study, understands
what telemetry is collected, and can withdraw its data.

Use each partner's own failure traces only in that partner's authorized environment. Collect the
minimum evidence needed; redact content before export; never commit customer traces, credentials,
personal data, or partner identities. Public case studies require separate written approval.

### Protocol

1. Record role, prior replay experience, application stack, and success criterion.
2. Time installation from the published package to the first passing fixture-only replay.
3. Capture one naturally occurring failure or a partner-selected historical failure. Do not invent
   a failure and count it as production validation.
4. Record the investigator's initial hypothesis and start time before using ReplayGuard.
5. Run replay/diagnosis and retain checksums of sanitized evidence and commands used.
6. Record whether the root cause was correctly localized and independently confirmed by the team.
7. Measure time to confirmed cause using the team's normal workflow and ReplayGuard on comparable
   failures, or use a randomized crossover on the same sanitized incident when feasible.
8. Interview the participant after one week and again after four weeks; record actual retained use,
   prevented harmful changes, blockers, and support time.

### Acceptance gates

- Five completed partner installations.
- Three independently confirmed real-failure replays.
- Two measured debugging-time reductions, with raw durations and method reported rather than only
  testimonials.
- At least one retained weekly use event per qualifying team at week four.
- Production-tap demand is validated only when a partner actually chooses it for an authorized
  workload; implementation availability alone does not satisfy L2's demand gate.

Use one record per session:

```yaml
study_id: RG-DP-YYYY-NN
partner_pseudonym: ""
consent_record: private-reference-only
application_stack: []
frameworks: []
started_at: ""
first_replay_at: ""
installation_minutes: null
real_failure: false
failure_evidence_sha256: ""
root_cause_confirmed_by_partner: false
normal_workflow_minutes: null
replayguard_minutes: null
measurement_method: ""
week_1_used: false
week_4_used: false
prevented_harmful_change: false
support_minutes: null
notes_redacted: ""
```

## Decision ledger

The product may be described as engineering-complete for its implemented features. Do not describe
it as independently security-reviewed, penetration-tested, production-validated, retained by design
partners, or commercially ready until the corresponding signed evidence satisfies the gates above.

Current state:

| Gate | Required evidence | Status |
|---|---|---|
| Independent security review | Signed scoped report and retest | Open |
| No unresolved critical/high findings | Private finding ledger | Open |
| Five partner installations | Five consented study records | Open |
| Three real-failure replays | Checksummed evidence + partner confirmation | Open |
| Two measured time reductions | Raw paired/crossover durations | Open |
| Four-week retained use | Follow-up records | Open |

