# Experimental: claim/evidence graph in `verify diagnose`

```powershell
verify diagnose RUN_ID --experimental-claim-graph
```

Adds an `experimental_claim_graph` array to the JSON output alongside the existing deterministic
`suspects` list. It never changes `suspects`, never changes the process exit code, and is omitted
from the output entirely unless the flag is passed — default `verify diagnose` behavior is
unaffected.

## What it is

`replayguard.claim_graph` (Layer 3 of the stacked-diagnostics research — see
`docs/RESEARCH_TRAIL_DIAGNOSIS.md`) is a training-free local signal: it extracts explicit
consequential/finalized commitments from each span's text, links them to earlier evidence by
rarity-weighted lexical overlap, and flags claims with weak or missing support. It makes no API
calls and cannot access gold labels or metadata. Each candidate carries a `CLAIM001` evidence
record with the claim excerpt and any linked support/reuse locations.

## Measured numbers (location-only F1, not the TRAIL joint span+category metric)

| Corpus | Baseline F1 | Claim graph F1 |
|---|---:|---:|
| TRAIL, 148 traces | 27.79% | 31.48% |
| TELBench, 1,000 cases | 13.13% | 40.04% |
| AgentRx, 73 trajectories | 1.02% | 8.43% |

It is the only research layer measured to beat the ReplayGuard location baseline on all three
independent external corpora (full detail and methodology in `docs/RESEARCH_TRAIL_DIAGNOSIS.md`).

## Why it's opt-in, not a default

- It has **not** been validated as a universal replacement for or improvement on the deterministic
  baseline outside these three benchmark corpora — no design-partner or production trace has ever
  used it.
- It reports **location only**, not category, so it cannot be scored against TRAIL's joint metric
  the way the deterministic engine can.
- It is explicitly excluded from any exit-code decision. Treat its output as a lead worth a human
  look, not a finding.
