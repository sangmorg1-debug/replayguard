"""Static-only client and manifest scanner for the official MCP Registry."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .mcp_scanner import Finding, SEVERITY
from .threat_mapping import mapping_for_rule

DEFAULT_ENDPOINT = "https://registry.modelcontextprotocol.io/v0.1/servers"


@dataclass(slots=True)
class RegistrySnapshot:
    endpoint: str
    retrieved_at: str
    pages: int
    records: list[dict[str, Any]]
    cursors: list[str]
    response_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RegistryClient:
    def __init__(self, endpoint: str = DEFAULT_ENDPOINT,
                 fetch: Callable[[str], dict[str, Any]] | None = None,
                 progress: Callable[[int, int], None] | None = None) -> None:
        self.endpoint = endpoint.rstrip("?")
        self.fetch = fetch or self._fetch
        self.progress = progress

    @staticmethod
    def _fetch(url: str) -> dict[str, Any]:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "ReplayGuard-Registry-Sweep/1.0"})
        with urlopen(request, timeout=60) as response:
            return json.load(response)

    def snapshot(self, *, limit: int = 100, max_pages: int | None = None) -> RegistrySnapshot:
        if not 1 <= limit <= 100:
            raise ValueError("registry page limit must be between 1 and 100")
        records: list[dict[str, Any]] = []; cursors: list[str] = []; raw_pages: list[dict[str, Any]] = []
        cursor: str | None = None; seen: set[str] = set()
        while True:
            query = {"limit": limit}
            if cursor: query["cursor"] = cursor
            body = self.fetch(f"{self.endpoint}?{urlencode(query)}")
            if not isinstance(body.get("servers"), list) or not isinstance(body.get("metadata"), dict):
                raise ValueError("registry response must contain servers[] and metadata")
            raw_pages.append(body); records.extend(body["servers"])
            if self.progress: self.progress(len(raw_pages), len(records))
            next_cursor = body["metadata"].get("nextCursor")
            if not next_cursor: break
            if not isinstance(next_cursor, str) or next_cursor in seen:
                raise ValueError("registry returned an invalid or repeated nextCursor")
            seen.add(next_cursor); cursors.append(next_cursor); cursor = next_cursor
            if max_pages is not None and len(raw_pages) >= max_pages: break
        digest = hashlib.sha256(json.dumps(raw_pages, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        return RegistrySnapshot(self.endpoint, datetime.now(timezone.utc).isoformat(), len(raw_pages), records, cursors, digest)


def _finding(rule: str, severity: str, title: str, server: str, evidence: str,
             impact: str, remediation: str, category: str) -> Finding:
    return Finding(rule, severity, title, server, evidence[:240],
                   ["Inspect the pinned registry snapshot.", f"Manually verify {rule} without connecting to or invoking the server."],
                   "The client installs the package or connects to the declared remote.", impact, remediation, category,
                   **mapping_for_rule(rule))


def scan_server_manifest(record: dict[str, Any]) -> list[Finding]:
    server = record.get("server") if isinstance(record.get("server"), dict) else {}
    name = str(server.get("name") or "unknown-server"); findings: list[Finding] = []
    schema = str(server.get("$schema") or "")
    parsed_schema = urlparse(schema)
    if parsed_schema.scheme != "https" or parsed_schema.hostname not in {"static.modelcontextprotocol.io", "registry.modelcontextprotocol.io"}:
        findings.append(_finding("RGM001", "medium", "Manifest does not pin the official HTTPS schema", name, schema,
                                 "Clients may validate against an absent or untrusted schema.", "Pin an official static MCP server schema URL.", "supply-chain"))
    for remote in server.get("remotes") or []:
        if not isinstance(remote, dict): continue
        url = str(remote.get("url") or ""); parsed = urlparse(url)
        if parsed.scheme != "https":
            findings.append(_finding("RGM002", "high", "Remote transport is not HTTPS", name, url,
                                     "Traffic or credentials may be intercepted or modified.", "Publish only TLS-protected remote endpoints.", "transport-security"))
        if parsed.username or parsed.password:
            findings.append(_finding("RGM003", "critical", "Remote URL embeds credentials", name, url,
                                     "Registry consumers may log or disclose embedded credentials.", "Remove credentials and use an explicit secure authentication flow.", "credential-exposure"))
    for package in server.get("packages") or []:
        if not isinstance(package, dict): continue
        identifier = str(package.get("identifier") or "")
        version = str(package.get("version") or "")
        if not identifier or not version:
            findings.append(_finding("RGM004", "high", "Package reference is not version-pinned", name, f"{identifier}@{version}",
                                     "A mutable or ambiguous package may resolve to unexpected code.", "Provide an immutable package identifier and version.", "supply-chain"))
        for environment in package.get("environmentVariables") or []:
            if not isinstance(environment, dict): continue
            value = environment.get("value"); variable = str(environment.get("name") or "")
            placeholder = isinstance(value, str) and re.fullmatch(r"\{[^{}]+\}", value)
            benign_literal = str(value).lower() in {"true", "false", "0", "1", "none", "null", "dummy", "test", "changeme"}
            if value not in (None, "") and not placeholder and not benign_literal and re.search(r"(?i)(secret|token|password|credential|api.?key|private.?key|authorization)", variable):
                findings.append(_finding("RGM005", "critical", "Package manifest embeds an environment value", name,
                                         variable or "environment variable",
                                         "A credential or deployment-specific value may be redistributed.", "Declare an input placeholder and mark secret inputs appropriately.", "credential-exposure"))
    return findings


def aggregate_registry(snapshot: RegistrySnapshot) -> dict[str, Any]:
    findings: list[Finding] = []; names = set(); latest = 0
    statuses: Counter[str] = Counter(); transports: Counter[str] = Counter(); packages: Counter[str] = Counter(); schemas: Counter[str] = Counter()
    for record in snapshot.records:
        server = record.get("server") or {}; name = str(server.get("name") or "")
        if name: names.add(name)
        official = (record.get("_meta") or {}).get("io.modelcontextprotocol.registry/official", {})
        statuses[str(official.get("status") or "unknown")] += 1; latest += int(official.get("isLatest") is True)
        schemas[str(server.get("$schema") or "missing")] += 1
        transports.update(str(item.get("type") or "unknown") for item in server.get("remotes") or [] if isinstance(item, dict))
        packages.update(str(item.get("registryType") or "unknown") for item in server.get("packages") or [] if isinstance(item, dict))
        findings.extend(scan_server_manifest(record))
    severity = Counter(item.severity for item in findings); rules = Counter(item.rule_id for item in findings)
    body = {"format": "replayguard-mcp-registry-sweep-v1", "scope": "static distribution manifests only",
            "safety": "No packages installed, remote servers contacted, or MCP tools invoked.",
            "endpoint": snapshot.endpoint, "retrieved_at": snapshot.retrieved_at, "snapshot_sha256": snapshot.response_sha256,
            "pages": snapshot.pages, "records": len(snapshot.records), "unique_servers": len(names), "latest_records": latest,
            "status_counts": dict(sorted(statuses.items())), "transport_counts": dict(sorted(transports.items())),
            "package_registry_counts": dict(sorted(packages.items())), "schema_counts": dict(sorted(schemas.items())),
            "finding_counts_by_severity": {key: severity.get(key, 0) for key in SEVERITY},
            "finding_counts_by_rule": dict(sorted(rules.items())), "findings_total": len(findings),
            "threat_mappings": {rule: mapping_for_rule(rule) for rule in sorted(rules)},
            "publication_status": "aggregate-only; individual findings require manual confirmation and responsible disclosure"}
    body["report_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return body


def render_registry_markdown(report: dict[str, Any]) -> str:
    lines = ["# ReplayGuard MCP Registry static sweep", "",
             f"- Retrieved: `{report['retrieved_at']}`", f"- Endpoint: `{report['endpoint']}`",
             f"- Snapshot SHA-256: `{report['snapshot_sha256']}`", f"- Pages: **{report['pages']}**",
             f"- Manifest records: **{report['records']}**", f"- Unique servers: **{report['unique_servers']}**",
             f"- Static findings: **{report['findings_total']}**", "",
             "No packages were installed, remote servers contacted, or MCP tools invoked.",
             "This report covers distribution manifests only, not server behavior or tool schemas.", "",
             "## Aggregate findings", ""]
    for rule, count in report["finding_counts_by_rule"].items():
        mapping = report["threat_mappings"][rule]
        atlas = ", ".join(item["id"] for item in mapping["atlas_techniques"]) or "—"
        owasp = ", ".join(item["id"] for item in mapping["owasp_risks"]) or "—"
        lines.append(f"- `{rule}`: {count} (ATLAS: {atlas}; OWASP: {owasp})")
    if not report["finding_counts_by_rule"]: lines.append("- None")
    lines.extend(["", "Individual server details are intentionally excluded. Manually confirm any finding and follow the responsible disclosure process in SECURITY.md.", ""])
    return "\n".join(lines)
