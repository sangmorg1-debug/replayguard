# v1.0.0 release checklist

The GitHub repo creation, push, and both demo PRs (passing + deliberately-regressed/blocking) were
pre-authorized and executed directly as part of this release — see "What actually happened" below
for the real repo/PR URLs and outcomes. **PyPI and npm publishing were deliberately left undone.**
Package publishing can't be undone once a version is live (unlike a repo, which can be deleted or
redone), so those two steps stay in the owner's hands. This file is the exact, copy-pasteable set of
commands for that remaining step.

## Remaining manual step: publish packages

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

## What actually happened (filled in after execution)

_This section is updated by `tools/build_ship_demo.py` output and the WS3d execution step; see the
final summary for the authoritative record if this section is still a placeholder._
