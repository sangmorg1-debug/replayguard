from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .threat_mapping import mapping_for_rule

SEVERITY = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
INJECTION = re.compile(r"(?i)(ignore (?:all|any|the) (?:previous|prior)|system prompt|do not tell|hidden instruction|"
                       r"(?:send|upload).{0,40}(?:secret|token|credential|private|sensitive|data|file)|exfiltrat|"
                       r"override (?:the )?user|act as|you must|follow these instructions)")
DESTRUCTIVE = re.compile(r"(?i)(delete|remove|drop|erase|overwrite|write|send|transfer|pay|purchase|execute|shell|command|deploy|publish)")
SENSITIVE = re.compile(r"(?i)(password|secret|token|credential|private.?key|api.?key|authorization)")


@dataclass
class Finding:
    rule_id: str
    severity: str
    title: str
    tool: str | None
    evidence: str
    reproduction: list[str]
    preconditions: str
    impact: str
    remediation: str
    category: str
    deterministic: bool = True
    atlas_techniques: list[dict[str, str]] = field(default_factory=list)
    owasp_risks: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ScanReport:
    target: str
    findings: list[Finding]
    tools_scanned: int
    suppressed: int = 0
    protocol_checks: dict[str, bool] = field(default_factory=dict)

    @property
    def max_severity(self) -> str:
        return max((item.severity for item in self.findings), key=SEVERITY.get, default="info")

    def to_dict(self) -> dict[str, Any]:
        body = {"format": "replayguard-mcp-scan-v1", "target": self.target,
                "tools_scanned": self.tools_scanned, "suppressed": self.suppressed,
                "max_severity": self.max_severity, "protocol_checks": self.protocol_checks,
                "findings": [asdict(item) for item in self.findings]}
        body["report_sha256"] = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return body


class MCPScanner:
    def scan(self, tools: list[dict[str, Any]], *, target: str = "manifest",
             outputs: dict[str, Any] | None = None, transcript: list[dict[str, Any]] | None = None,
             suppressions: list[dict[str, str]] | None = None) -> ScanReport:
        findings: list[Finding] = []
        names: set[str] = set()
        for tool in tools:
            name = str(tool.get("name", ""))
            description = str(tool.get("description", ""))
            schema = tool.get("inputSchema")
            if not name or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", name):
                findings.append(self._f("MCP001", "high", "Invalid or missing tool name", name or None, repr(name),
                    "Protocol clients may misroute or collide tools.", "Use a stable, nonempty, low-cardinality tool name.", "protocol"))
            if name in names:
                findings.append(self._f("MCP002", "high", "Duplicate tool name", name, name,
                    "A client receives the ambiguous tools/list response.", "Use unique names and namespace tools across servers.", "tool-shadowing"))
            names.add(name)
            if not isinstance(schema, dict) or schema.get("type") != "object":
                findings.append(self._f("MCP003", "high", "Missing strict object input schema", name, repr(schema),
                    "An LLM or attacker supplies malformed arguments.", "Declare an object JSON Schema with typed properties and required fields.", "input-validation"))
                schema = {"properties": {}}
            if schema.get("additionalProperties") is not False:
                findings.append(self._f("MCP004", "medium", "Additional arguments are not rejected", name, "additionalProperties is not false",
                    "Unexpected arguments reach server-side handlers.", "Set additionalProperties to false and reject undeclared fields.", "input-validation"))
            if INJECTION.search(description):
                findings.append(self._f("MCP005", "critical", "Tool description contains instruction-like content", name, description[:240],
                    "The description is exposed to an agent model.", "Remove behavioral instructions; describe only purpose, inputs, and outputs.", "tool-poisoning"))
            annotations = tool.get("annotations") or {}
            destructive = bool(DESTRUCTIVE.search(name + " " + description))
            if annotations.get("readOnlyHint") is True and (annotations.get("destructiveHint") is True or destructive):
                findings.append(self._f("MCP006", "high", "Contradictory read-only annotation", name, repr(annotations),
                    "A client trusts unverified annotations.", "Correct annotations and enforce authorization independently of hints.", "excessive-agency"))
            if destructive and annotations.get("destructiveHint", True) and not tool.get("_meta", {}).get("requiresConfirmation"):
                findings.append(self._f("MCP007", "high", "Consequential tool lacks confirmation metadata", name, repr(annotations),
                    "The agent is authorized to invoke the tool.", "Require explicit confirmation and server-side authorization for consequential calls.", "excessive-agency"))
            properties = schema.get("properties", {}) if isinstance(schema.get("properties", {}), dict) else {}
            for parameter, definition in properties.items():
                definition = definition if isinstance(definition, dict) else {}
                lower = parameter.lower()
                if any(word in lower for word in ("path", "file", "directory")) and not any(k in definition for k in ("pattern", "enum")):
                    findings.append(self._f("MCP008", "high", "Path parameter lacks confinement", name, parameter,
                        "An attacker controls the path argument.", "Resolve paths, enforce an approved root, reject traversal, and use schema constraints.", "path-traversal"))
                if any(word in lower for word in ("url", "uri", "endpoint", "host")) and not any(k in definition for k in ("pattern", "enum")):
                    findings.append(self._f("MCP009", "high", "Network destination lacks an allowlist", name, parameter,
                        "The server can make outbound requests.", "Allowlist schemes and destinations; block loopback, private, link-local, and metadata ranges.", "ssrf"))
                if any(word in lower for word in ("command", "shell", "script", "sql", "code")):
                    findings.append(self._f("MCP010", "critical", "Raw execution parameter exposed", name, parameter,
                        "An attacker influences the execution argument.", "Replace raw execution with a narrow operation enum and parameterized implementation.", "code-execution"))
                if SENSITIVE.search(parameter) and not definition.get("writeOnly"):
                    findings.append(self._f("MCP011", "high", "Sensitive argument is not marked write-only", name, parameter,
                        "Arguments are logged or reflected.", "Avoid passing secrets as tool arguments; otherwise mark and redact them end-to-end.", "credential-exposure"))
        for name, output in (outputs or {}).items():
            rendered = json.dumps(output, ensure_ascii=False, default=repr)
            if INJECTION.search(rendered):
                findings.append(self._f("MCP012", "critical", "Tool output contains indirect prompt injection", name, rendered[:240],
                    "Tool output is added to model context.", "Treat output as untrusted data, delimit it, filter instructions, and restrict downstream tools.", "indirect-prompt-injection"))
            if SENSITIVE.search(rendered):
                findings.append(self._f("MCP013", "high", "Tool output may expose credentials", name, rendered[:240],
                    "The tool can access sensitive material.", "Return only required fields and redact credentials before serialization.", "credential-exposure"))
        checks = self._validate_transcript(transcript or [])
        if transcript and not all(checks.values()):
            for check, passed in checks.items():
                if not passed:
                    findings.append(self._f("MCP014", "medium", f"Protocol check failed: {check}", None, check,
                        "A client exercises normal protocol behavior.", "Return JSON-RPC 2.0 responses with matching IDs, valid results, and structured errors.", "protocol"))
        report = ScanReport(target, findings, len(tools), protocol_checks=checks)
        self._suppress(report, suppressions or [])
        return report

    def scan_stdio(self, command: list[str], *, timeout: float = 10) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Perform only initialize and tools/list. Never sends tools/call."""
        with tempfile.TemporaryDirectory(prefix="replayguard-mcp-") as cwd:
            allowed_env = {key: value for key, value in os.environ.items() if key.upper() in {
                "PATH", "SYSTEMROOT", "COMSPEC", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA", "HOME"}}
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True, cwd=cwd, env=allowed_env)
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "replayguard-scanner", "version": "0.1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            ]
            payload = "".join(json.dumps(message) + "\n" for message in messages)
            try:
                stdout, stderr = process.communicate(payload, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                process.kill()
                remaining_out, remaining_err = process.communicate()
                partial_out = exc.output.decode() if isinstance(exc.output, bytes) else (exc.output or "")
                partial_err = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                stdout, stderr = partial_out + (remaining_out or ""), partial_err + (remaining_err or "")
            transcript = []
            for line in stdout.splitlines():
                try: transcript.append(json.loads(line))
                except json.JSONDecodeError: continue
            response = next((item for item in transcript if item.get("id") == 2), None)
            if not response or "result" not in response or not isinstance(response["result"].get("tools"), list):
                raise RuntimeError(f"MCP server did not return a valid tools/list response; exit={process.returncode}; stderr={stderr[-500:]}")
            return response["result"]["tools"], transcript

    def _validate_transcript(self, transcript: list[dict[str, Any]]) -> dict[str, bool]:
        if not transcript: return {}
        responses = [item for item in transcript if "method" not in item]
        return {"jsonrpc_version": all(item.get("jsonrpc") == "2.0" for item in transcript),
                "response_ids": bool(responses) and all("id" in item for item in responses),
                "result_or_error": bool(responses) and all(("result" in item) ^ ("error" in item) for item in responses),
                "structured_errors": all(not item.get("error") or isinstance(item["error"].get("code"), int) for item in responses)}

    def _suppress(self, report: ScanReport, suppressions: list[dict[str, str]]) -> None:
        kept = []
        for finding in report.findings:
            matched = any((item.get("rule_id") in (None, finding.rule_id)) and
                          fnmatch.fnmatch(finding.tool or "", item.get("tool", "*")) for item in suppressions)
            if matched: report.suppressed += 1
            else: kept.append(finding)
        report.findings = kept

    @staticmethod
    def _f(rule: str, severity: str, title: str, tool: str | None, evidence: str,
           preconditions: str, remediation: str, category: str) -> Finding:
        target = tool or "server"
        return Finding(rule, severity, title, tool, evidence,
                       [f"Run verify mcp-scan against the same manifest or server.", f"Inspect `{target}` and confirm rule {rule}."],
                       preconditions, f"May enable {category.replace('-', ' ')} through `{target}`.", remediation, category,
                       **mapping_for_rule(rule))


def render_scan_markdown(report: ScanReport) -> str:
    lines = ["# ReplayGuard MCP security report", "", f"- Target: `{report.target}`",
             f"- Tools scanned: **{report.tools_scanned}**", f"- Maximum severity: **{report.max_severity}**",
             f"- Findings: **{len(report.findings)}**", f"- Suppressed: **{report.suppressed}**", ""]
    for finding in sorted(report.findings, key=lambda item: (-SEVERITY[item.severity], item.rule_id, item.tool or "")):
        evidence = finding.evidence.replace("`", "'")
        lines.extend([f"## {finding.severity.upper()} {finding.rule_id}: {finding.title}", "",
                      f"**Tool:** `{finding.tool or 'server'}`  ", f"**Category:** {finding.category}  ",
                      f"**MITRE ATLAS:** {', '.join(item['id'] for item in finding.atlas_techniques) or '—'}  ",
                      f"**OWASP:** {', '.join(item['id'] for item in finding.owasp_risks) or '—'}  ",
                      f"**Evidence:** `{evidence}`  ",
                      f"**Preconditions:** {finding.preconditions}  ", f"**Impact:** {finding.impact}  ",
                      f"**Remediation:** {finding.remediation}", "", "Reproduction:", ""])
        lines.extend(f"1. {step}" for step in finding.reproduction)
        lines.append("")
    return "\n".join(lines)
