# v1.0.0 release checklist

The GitHub repo creation, push, and both demo PRs (passing + deliberately-regressed/blocking) were
pre-authorized and executed directly as part of this release — see "What actually happened" below.
**One step needs owner action before the real-PR demo can finish: the GitHub account's Actions runs
are blocked by a billing issue** (see below) — this is new, not something that was known going in.
**PyPI and npm publishing were also deliberately left undone.** Package publishing can't be undone
once a version is live (unlike a repo, which can be deleted or redone), so that step stays in the
owner's hands regardless. This file is the exact, copy-pasteable set of commands for both remaining
steps.

## Remaining manual step 1: resolve GitHub Actions billing lock (blocks the real-PR demo)

Both demo PR checks failed immediately with: **"The job was not started because your account is
locked due to a billing issue."** This is a GitHub account-level billing block on
`sangmorg1-debug`, unrelated to any code in this repository — it could not be worked around from
here, and no workaround was attempted (bypassing it would defeat the point of the real-PR demo).

1. Go to https://github.com/settings/billing (or the organization billing settings if applicable)
   and resolve the flagged issue (expired card, overdue invoice, spending limit, etc.).
2. Re-run both PR checks: `gh pr checks 1 --repo sangmorg1-debug/replayguard --watch` and
   `gh pr checks 2 --repo sangmorg1-debug/replayguard --watch`, or push an empty commit to each
   branch (`git commit --allow-empty -m "retrigger" && git push`) if re-runs don't pick up cleanly.
3. Confirm: PR #1 (`demo/passing-check`) shows the required check green; PR #2
   (`demo/blocking-check`) shows it red/blocked with the `exact`, `max_cost_usd`, and
   `security_invariant` failures visible in the job summary.
4. **Merge only the `.gitattributes` file from PR #1**, not the workflow change on that branch —
   the branch wires a static candidate map into `.github/workflows/replayguard.yml` to prove a
   genuine pass under the fixed (see below) semantics, and that wiring must not land on `main`
   permanently: a frozen candidate map compared against every future PR forever would trivially
   pass regardless of what actually changed, which is a different shape of the same false-green
   problem this release fixed. Cherry-pick or manually re-apply just `.gitattributes`, or merge the
   PR and immediately revert the workflow diff in a follow-up commit. Leave PR #2 open and
   unmerged — it exists only as the blocking-check artifact; delete both demo branches afterward
   once you're done with them.

Heads-up: once `.gitattributes` (`* text=auto eol=lf`) merges, the next time any file with mixed
line endings is touched, Git will show a renormalization diff (content unchanged, only line-ending
metadata). That's expected, not a regression — `git add --renormalize .` in a follow-up commit
clears it in one pass if it's noisy.

## Remaining manual step 2: publish packages

### PyPI (`replayguard` 1.0.0)

```powershell
python -m pip install --upgrade build twine
python -m build --no-isolation
python -m twine check dist/replayguard-1.0.0*
python -m twine upload dist/replayguard-1.0.0*
```

Requires a PyPI account with a configured API token (`~/.pypirc` or `TWINE_USERNAME=__token__` /
`TWINE_PASSWORD=pypi-...`). Verify `pip install replayguard==1.0.0` from a clean virtualenv against
the real index afterward.

### npm (`@replayguard/sdk` 1.0.0)

```powershell
cd sdk/typescript
npm ci
npm test
npm publish --access public
```

Requires `npm login` under an account with publish rights to the `@replayguard` scope (or adjust the
`name` field in `sdk/typescript/package.json` to an unscoped or owned-scope name before publishing
if `@replayguard` is unavailable). Verify `npm view @replayguard/sdk` afterward.

## Final review before/after publishing

- Confirm the created repo and both PR reports contain no leaked content: `.verify/ship-demo/*/report.md`
  and `results.json` are redacted by `Redactor` before being written, but do a manual read before
  treating them as public — see `docs/PRIVACY.md`.
- If you want to redo the repo/PR demo differently (different account, different repo name, private
  instead of public): delete the repo (`gh repo delete <owner>/<repo>`) and start over; the local
  `.verify/ship-demo/` artifacts and `tools/build_ship_demo.py` are reproducible and don't need to
  change.
- After PyPI/npm publish, update `docs/L5_EXTERNAL_VALIDATION.md`'s ledger only once real gates
  (security review, design partners) actually close — publishing packages does not itself satisfy
  any L5 gate.

## What actually happened

Executed 2026-07-21:

- Created public repo `sangmorg1-debug/replayguard`, pushed `main` (196 files, one commit).
- Opened PR #1 (`demo/passing-check`, adds `.gitattributes`):
  https://github.com/sangmorg1-debug/replayguard/pull/1
- Opened PR #2 (`demo/blocking-check`, wires the deliberately regressed candidate map, **not
  intended to be merged**): https://github.com/sangmorg1-debug/replayguard/pull/2
- **Both required-check runs failed identically and immediately** with: *"The job was not started
  because your account is locked due to a billing issue."* This is a GitHub account-level billing
  block on `sangmorg1-debug`, unrelated to the code — the workflow never actually executed on either
  PR. No workaround was attempted; see "Remaining manual step 1" above. Until the billing issue is
  resolved and both checks are re-run, **the real-PR demo is not actually complete** — the repo and
  PRs are real, but neither check has genuinely passed or blocked yet.
- Local, non-GitHub-hosted proof remains valid and unaffected by this: `.verify/ship-demo/ci-passing/`
  (`passed: true`, 106/106, against a real unchanged candidate map) and `.verify/ship-demo/ci-blocked/`
  (`passed: false`, exit 1, 105/106, failing `exact`/`max_cost_usd`/`security_invariant` on case
  `bfcl:live_simple_0-0-0`), reproducible via `python tools/build_ship_demo.py` and the two `verify
  ci` commands at the top of this repo's `tools/build_ship_demo.py` docstring.
- **Post-release code review fixed a false-green defect** in the gate these demos exercise: without
  a supplied `--candidate-map`, `SuiteRunner` used to compare the baseline against itself and
  silently pass — meaning the default GitHub Action, installed with no extra wiring, could report
  SAFE TO MERGE regardless of what a PR actually changed. Both demo artifacts above and both demo
  branches on GitHub were rebuilt against the fix (a case with configured evaluations and no real
  candidate now reports undetermined, not a pass). See the "SuiteRunner silently passed cases with
  no candidate supplied" commit on `main` and the updated demo branches.
