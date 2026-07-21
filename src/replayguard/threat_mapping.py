"""Pinned MITRE ATLAS and OWASP GenAI mappings for ReplayGuard controls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ATLAS_SOURCE = {
    "format": "STIX 2.1",
    "repository": "https://github.com/mitre-atlas/atlas-navigator-data",
    "revision": "2f55d5fd4b040f109692d066bfbccda4501eb724",
    "url": "https://raw.githubusercontent.com/mitre-atlas/atlas-navigator-data/2f55d5fd4b040f109692d066bfbccda4501eb724/dist/stix-atlas.json",
    "sha256": "a1bd782257de3c8591797ac863aa9b37fe4ae42ef9284bee98bfc2661fdd1c06",
}
OWASP_SOURCE = {
    "release": "OWASP Top 10 for LLM Applications 2025",
    "url": "https://genai.owasp.org/llm-top-10/",
}

ATLAS = {
    "AML.T0010": "AI Supply Chain Compromise",
    "AML.T0010.005": "AI Agent Tool",
    "AML.T0011.002": "Poisoned AI Agent Tool",
    "AML.T0034": "Cost Harvesting",
    "AML.T0034.002": "Agentic Resource Consumption",
    "AML.T0050": "Command and Scripting Interpreter",
    "AML.T0051.001": "Indirect",
    "AML.T0053": "AI Agent Tool Invocation",
    "AML.T0055": "Unsecured Credentials",
    "AML.T0057": "LLM Data Leakage",
    "AML.T0072": "Reverse Shell",
    "AML.T0080": "AI Agent Context Poisoning",
    "AML.T0080.000": "Memory",
    "AML.T0081": "Modify AI Agent Configuration",
    "AML.T0083": "Credentials from AI Agent Configuration",
    "AML.T0086": "Exfiltration via AI Agent Tool Invocation",
    "AML.T0097": "Virtualization/Sandbox Evasion",
    "AML.T0098": "AI Agent Tool Credential Harvesting",
    "AML.T0099": "AI Agent Tool Data Poisoning",
    "AML.T0101": "Data Destruction via AI Agent Tool Invocation",
    "AML.T0104": "Publish Poisoned AI Agent Tool",
    "AML.T0105": "Escape to Host",
    "AML.T0109": "AI Supply Chain Rug Pull",
    "AML.T0110": "AI Agent Tool Poisoning",
    "AML.T0111": "AI Supply Chain Reputation Inflation",
}
OWASP = {
    "LLM01:2025": "Prompt Injection",
    "LLM02:2025": "Sensitive Information Disclosure",
    "LLM03:2025": "Supply Chain",
    "LLM04:2025": "Data and Model Poisoning",
    "LLM05:2025": "Improper Output Handling",
    "LLM06:2025": "Excessive Agency",
    "LLM07:2025": "System Prompt Leakage",
    "LLM08:2025": "Vector and Embedding Weaknesses",
    "LLM09:2025": "Misinformation",
    "LLM10:2025": "Unbounded Consumption",
}

# A control may reduce several techniques. These are defensive coverage claims, not
# assertions that a finding proves an adversary used the mapped technique.
RULE_MAPPINGS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "MCP001": ((), ("LLM05:2025",)),
    "MCP002": (("AML.T0010.005",), ("LLM03:2025",)),
    "MCP003": ((), ("LLM05:2025",)),
    "MCP004": ((), ("LLM05:2025",)),
    "MCP005": (("AML.T0110",), ("LLM01:2025", "LLM06:2025")),
    "MCP006": (("AML.T0053",), ("LLM06:2025",)),
    "MCP007": (("AML.T0101",), ("LLM06:2025",)),
    "MCP008": (("AML.T0053",), ("LLM05:2025", "LLM06:2025")),
    "MCP009": (("AML.T0053",), ("LLM05:2025", "LLM06:2025")),
    "MCP010": (("AML.T0050", "AML.T0072"), ("LLM05:2025", "LLM06:2025")),
    "MCP011": (("AML.T0083",), ("LLM02:2025",)),
    "MCP012": (("AML.T0051.001",), ("LLM01:2025",)),
    "MCP013": (("AML.T0057",), ("LLM02:2025",)),
    "MCP014": ((), ("LLM05:2025",)),
    "RGM001": (("AML.T0010.005",), ("LLM03:2025",)),
    "RGM002": (("AML.T0010",), ("LLM02:2025", "LLM03:2025")),
    "RGM003": (("AML.T0055",), ("LLM02:2025",)),
    "RGM004": (("AML.T0109",), ("LLM03:2025",)),
    "RGM005": (("AML.T0083",), ("LLM02:2025",)),
}

GATEWAY_MAPPINGS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "secret-exfiltration": (("AML.T0086",), ("LLM02:2025",)),
    "unsafe-shell": (("AML.T0050", "AML.T0072"), ("LLM05:2025", "LLM06:2025")),
    "path-boundary": (("AML.T0053",), ("LLM06:2025",)),
    "network-boundary": (("AML.T0086",), ("LLM06:2025",)),
    "recipient-boundary": (("AML.T0086",), ("LLM02:2025", "LLM06:2025")),
    "transaction-limit": (("AML.T0053",), ("LLM06:2025",)),
    "rate-limit": (("AML.T0034.002",), ("LLM10:2025",)),
    "retry-limit": (("AML.T0034.002",), ("LLM10:2025",)),
    "recursion-limit": (("AML.T0034.002",), ("LLM10:2025",)),
    "cost-limit": (("AML.T0034",), ("LLM10:2025",)),
    "missing-idempotency-key": (("AML.T0101",), ("LLM06:2025",)),
    "emergency-revocation": (("AML.T0053",), ("LLM06:2025",)),
    "human-approval": (("AML.T0053",), ("LLM06:2025",)),
    "unknown-high-risk": (("AML.T0053",), ("LLM06:2025",)),
    "no-matching-allow": (("AML.T0053",), ("LLM06:2025",)),
    "sandbox-unavailable": (("AML.T0097", "AML.T0105"), ("LLM06:2025",)),
    "gateway_error": ((), ("LLM06:2025",)),
    "audit_failure": ((), ("LLM06:2025",)),
}

GATEWAY_REASON_PREFIXES = tuple(GATEWAY_MAPPINGS)


def _items(ids: tuple[str, ...], catalog: dict[str, str]) -> list[dict[str, str]]:
    return [{"id": value, "name": catalog[value]} for value in ids]


def mapping_for_rule(rule_id: str) -> dict[str, list[dict[str, str]]]:
    atlas, owasp = RULE_MAPPINGS[rule_id]
    return {"atlas_techniques": _items(atlas, ATLAS), "owasp_risks": _items(owasp, OWASP)}


def mapping_for_gateway(reason: str) -> dict[str, list[dict[str, str]]]:
    pair = GATEWAY_MAPPINGS.get(reason)
    if pair is None:
        # User-authored policy reasons still represent the gateway's agency boundary.
        pair = (("AML.T0053",), ("LLM06:2025",))
    return {"atlas_techniques": _items(pair[0], ATLAS), "owasp_risks": _items(pair[1], OWASP)}


def coverage_matrix() -> dict[str, Any]:
    mapped_atlas = sorted({item for pair in (*RULE_MAPPINGS.values(), *GATEWAY_MAPPINGS.values()) for item in pair[0]})
    rows = []
    for control, pair in sorted({**RULE_MAPPINGS, **{f"gateway:{k}": v for k, v in GATEWAY_MAPPINGS.items()}}.items()):
        rows.append({"control": control, "atlas": list(pair[0]), "owasp": list(pair[1])})
    body: dict[str, Any] = {
        "format": "replayguard-threat-coverage-v1",
        "sources": {"atlas": ATLAS_SOURCE, "owasp": OWASP_SOURCE},
        "controls": rows,
        "summary": {"controls": len(rows), "unmapped_controls": 0,
                    "atlas_techniques_covered": len(mapped_atlas), "owasp_risks_covered": len({x for p in RULE_MAPPINGS.values() for x in p[1]} | {x for p in GATEWAY_MAPPINGS.values() for x in p[1]})},
        "known_gaps": [{"id": key, "name": ATLAS[key]} for key in sorted(set(ATLAS) - set(mapped_atlas))],
        "interpretation": "Mappings describe defensive control coverage; a match does not prove adversary attribution.",
    }
    body["report_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return body


def render_coverage_markdown(report: dict[str, Any]) -> str:
    lines = ["# ReplayGuard threat coverage matrix", "",
             f"- ATLAS revision: `{report['sources']['atlas']['revision']}`", f"- ATLAS STIX SHA-256: `{report['sources']['atlas']['sha256']}`",
             f"- OWASP release: {report['sources']['owasp']['release']}", f"- Controls mapped: **{report['summary']['controls']}**",
             f"- Unmapped controls: **{report['summary']['unmapped_controls']}**", "", report["interpretation"], "", "## Coverage", "",
             "| Control | MITRE ATLAS | OWASP |", "|---|---|---|"]
    for row in report["controls"]:
        lines.append(f"| `{row['control']}` | {', '.join(row['atlas']) or '—'} | {', '.join(row['owasp']) or '—'} |")
    lines.extend(["", "## Known ATLAS gaps", "", "Agent-relevant techniques in the pinned catalog that are not directly covered:", ""])
    lines.extend(f"- `{item['id']}` — {item['name']}" for item in report["known_gaps"])
    return "\n".join(lines) + "\n"


def write_coverage(output: str | Path) -> tuple[Path, Path]:
    root = Path(output); root.mkdir(parents=True, exist_ok=True); report = coverage_matrix()
    json_path, md_path = root / "coverage.json", root / "coverage.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_coverage_markdown(report), encoding="utf-8")
    return json_path, md_path
