# X2 threat mapping

ReplayGuard findings and runtime decisions include `atlas_techniques` and `owasp_risks` arrays.
These mappings describe the attacks a defensive control can reduce; they do not claim that a
finding proves adversary activity or attribution.

Run:

```console
verify threat-map --output .verify/threat-mapping
```

This writes `coverage.json` for automation and `coverage.md` for review. The report includes
every scanner, Registry, and built-in gateway control, plus agent-relevant techniques in the
pinned ATLAS catalog that ReplayGuard does not directly cover.

The authoritative ATLAS input is the official STIX 2.1 distribution at revision
`2f55d5fd4b040f109692d066bfbccda4501eb724`; its expected SHA-256 is
`a1bd782257de3c8591797ac863aa9b37fe4ae42ef9284bee98bfc2661fdd1c06`. OWASP identifiers use
the OWASP Top 10 for LLM Applications 2025 release. CI validates that every shipped scanner and
registry rule has at least one mapping and that every identifier exists in the pinned catalogs.

Current limitations: the vendored ATLAS subset is deliberately scoped to agent-relevant
techniques. Refreshing the upstream pin requires a mapping review; it is never automatic.
Set `REPLAYGUARD_VERIFY_PUBLIC_DATA=1` when running pytest, or run
`python tools/verify_atlas_pin.py`, to download the real official STIX bundle and verify both
its checksum and every locally referenced technique name.
