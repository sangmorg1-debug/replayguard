"""Evidence inventory and EU AI Act coverage report generation.

This module organizes technical evidence. It does not determine legal applicability or compliance.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCES = {
    "regulation": {
        "title": "Regulation (EU) 2024/1689 (Artificial Intelligence Act)",
        "identifier": "CELEX:32024R1689",
        "version": "Official Journal L, 2024/1689, 12 July 2024",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689",
    },
    "gpai_code": {
        "title": "General-Purpose AI Code of Practice and Model Documentation Form",
        "identifier": "GPAI-Code-2025-07-10",
        "version": "Published 10 July 2025; Commission/AI Board adequacy confirmed",
        "url": "https://digital-strategy.ec.europa.eu/en/policies/contents-code-gpai",
        "model_documentation_form": "https://ec.europa.eu/newsroom/dae/redirection/document/118118",
    },
    "article_50_guidelines": {
        "title": "Guidelines on Article 50 transparency obligations",
        "identifier": "EC-Article-50-Guidelines-2026-07-20",
        "version": "Published 20 July 2026",
        "url": "https://digital-strategy.ec.europa.eu/en/library/guidelines-transparency-obligations-providers-and-deployers-ai-systems",
        "document": "https://ec.europa.eu/newsroom/dae/redirection/document/131215",
    },
}

OBLIGATIONS = [
    ("Article 53(1)(a)", "gpai", "Technical documentation: training/testing process and evaluation results", "evidence", ("trace-log", "ci-evidence", "rag-report", "aibom")),
    ("Article 53(1)(b); Annex XII", "gpai", "Information for downstream AI-system providers on capabilities and limitations", "partial", ("aibom", "ci-evidence", "rag-report")),
    ("Article 53(1)(c)", "gpai", "Copyright-compliance policy and machine-readable rights reservations", "process", ()),
    ("Article 53(1)(d)", "gpai", "Public summary of GPAI training content using the AI Office template", "partial", ("aibom",)),
    ("Article 53(3)", "gpai", "Cooperate with the Commission and competent authorities", "process", ()),
    ("Article 55(1)(a)", "gpai", "Standardised model evaluation and documented adversarial testing for systemic-risk GPAI", "evidence", ("ci-evidence", "rag-report", "security-report")),
    ("Article 55(1)(b)", "gpai", "Assess and mitigate systemic risks at Union level", "partial", ("security-report", "gateway-audit", "threat-coverage")),
    ("Article 55(1)(c)", "gpai", "Track, document, and report serious incidents without undue delay", "process", ("gateway-audit",)),
    ("Article 55(1)(d)", "gpai", "Adequate cybersecurity protection for model and infrastructure", "partial", ("security-report", "gateway-audit", "threat-coverage")),
    ("Article 50(1)", "provider", "Inform people when they interact directly with an AI system unless obvious", "process", ()),
    ("Article 50(2)", "provider", "Effective, interoperable, robust machine-readable marking of synthetic content", "process", ()),
    ("Article 50(3)", "deployer", "Inform people exposed to emotion recognition or biometric categorisation", "process", ()),
    ("Article 50(4)", "deployer", "Disclose deepfakes and certain public-interest AI-generated text", "process", ()),
    ("Article 50(5)", "provider", "Provide Article 50 information accessibly at first interaction or exposure", "process", ()),
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_kind(path: Path) -> str | None:
    try:
        if path.stat().st_size > 50_000_000:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    format_name = str(value.get("format", "")) if isinstance(value, dict) else ""
    if format_name == "replayguard-evidence-v1": return "ci-evidence"
    if format_name.startswith("replayguard-mcp-"): return "security-report"
    if format_name == "replayguard-threat-coverage-v1": return "threat-coverage"
    if isinstance(value, dict) and value.get("bomFormat") == "ReplayGuard-AIBOM": return "aibom"
    if isinstance(value, dict) and "provenance" in json.dumps(value) and "summary" in value: return "rag-report"
    if isinstance(value, dict) and {"id", "events"} <= set(value): return "trace-log"
    return None


def discover_artifacts(workspace: str | Path, output: str | Path) -> list[tuple[Path, str]]:
    root, destination = Path(workspace).resolve(), Path(output).resolve()
    candidates: list[tuple[Path, str]] = []
    search_roots = [root / ".verify"] if (root / ".verify").is_dir() else [root]
    for search_root in search_roots:
        for path in sorted(search_root.rglob("*")):
            if not path.is_file() or destination == path or destination in path.parents:
                continue
            kind = _json_kind(path) if path.suffix.lower() == ".json" else None
            if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"} and "gateway" in path.name.lower():
                kind = "gateway-audit"
            if kind: candidates.append((path, kind))
    return candidates


def build_pack(workspace: str | Path, output: str | Path, *, profile: str = "all") -> dict[str, Any]:
    root, out = Path(workspace).resolve(), Path(output).resolve()
    out.mkdir(parents=True, exist_ok=True); evidence_dir = out / "evidence"; evidence_dir.mkdir(exist_ok=True)
    artifacts = []
    for index, (source, kind) in enumerate(discover_artifacts(root, out), 1):
        target = evidence_dir / f"{index:04d}-{source.name}"
        shutil.copy2(source, target)
        artifacts.append({"id": f"E{index:04d}", "type": kind,
                          "source": str(source.relative_to(root)), "packaged": str(target.relative_to(out)),
                          "sha256": _sha(target), "bytes": target.stat().st_size})
    selected_profiles = {"gpai", "provider", "deployer"} if profile == "all" else {profile}
    coverage = []
    for reference, category, obligation, support, kinds in OBLIGATIONS:
        if category not in selected_profiles: continue
        ids = [item["id"] for item in artifacts if item["type"] in kinds]
        actual = support if ids or support == "process" else "missing-evidence"
        coverage.append({"reference": reference, "profile": category, "obligation": obligation,
                         "support": actual, "evidence": ids,
                         "automation_boundary": "Requires accountable human/legal process." if support == "process" else
                                                "Technical artifacts support but do not establish legal compliance."})
    body: dict[str, Any] = {
        "format": "replayguard-eu-ai-act-evidence-pack-v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "profile": profile, "workspace": str(root), "sources": SOURCES, "artifacts": artifacts, "coverage": coverage,
        "summary": {"artifacts": len(artifacts), "obligations": len(coverage),
                    "evidence": sum(row["support"] == "evidence" for row in coverage),
                    "partial": sum(row["support"] == "partial" for row in coverage),
                    "process": sum(row["support"] == "process" for row in coverage),
                    "missing_evidence": sum(row["support"] == "missing-evidence" for row in coverage)},
        "disclaimer": "Evidence organization only; not legal advice, a conformity assessment, or a compliance certification. Applicability and sufficiency require qualified human review.",
        "dates": {"article_50_applies": "2026-08-02", "gpai_commission_enforcement": "2026-08-02",
                  "legacy_gpai_model_deadline": "2027-08-02"},
    }
    digest_input = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    body["pack_sha256"] = hashlib.sha256(digest_input).hexdigest()
    (out / "pack.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    (out / "coverage.md").write_text(render_markdown(body), encoding="utf-8")
    return body


def render_markdown(pack: dict[str, Any]) -> str:
    lines = ["# ReplayGuard EU AI Act evidence pack", "", f"> {pack['disclaimer']}", "",
             f"- Profile: `{pack['profile']}`", f"- Evidence artifacts: **{pack['summary']['artifacts']}**",
             f"- Pack SHA-256: `{pack['pack_sha256']}`", "", "## Coverage", "",
             "| Reference | Support | Evidence | Automation boundary |", "|---|---|---|---|"]
    for row in pack["coverage"]:
        lines.append(f"| {row['reference']} — {row['obligation']} | **{row['support']}** | {', '.join(row['evidence']) or '—'} | {row['automation_boundary']} |")
    lines.extend(["", "## Source versions", ""])
    lines.extend(f"- **{value['title']}** — `{value['identifier']}` ({value['version']})" for value in pack["sources"].values())
    lines.extend(["", "## Important boundaries", "", "- ReplayGuard does not determine whether an organization, model, or system is in scope.",
                  "- Process rows cannot be completed by generated artifacts.", "- Partial and evidence rows still require review for accuracy, completeness, retention, and disclosure.",
                  "- Packaged evidence may contain sensitive information; protect it accordingly.", ""])
    return "\n".join(lines)
