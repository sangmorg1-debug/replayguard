"""Stateful, static-only monitoring for official MCP Registry snapshots."""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from .mcp_registry import RegistryClient, RegistrySnapshot, scan_server_manifest
from .mcp_scanner import SEVERITY


def _official(record: dict[str, Any]) -> dict[str, Any]:
    return (record.get("_meta") or {}).get("io.modelcontextprotocol.registry/official", {})


def _latest(snapshot: RegistrySnapshot) -> dict[str, dict[str, Any]]:
    result = {}
    for record in snapshot.records:
        server = record.get("server") if isinstance(record.get("server"), dict) else {}
        name = str(server.get("name") or "")
        if name and (_official(record).get("isLatest") is True or name not in result): result[name] = record
    return result


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _surface(server: dict[str, Any]) -> dict[str, set[str]]:
    surface: dict[str, set[str]] = {key: set() for key in ("remotes", "packages", "arguments", "inputs", "headers")}
    for remote in server.get("remotes") or []:
        if not isinstance(remote, dict): continue
        parsed = urlparse(str(remote.get("url") or ""))
        surface["remotes"].add(f"{remote.get('type','unknown')}:{parsed.scheme}://{parsed.netloc}{parsed.path}")
        for header in remote.get("headers") or []:
            if isinstance(header, dict): surface["headers"].add(str(header.get("name") or "unknown"))
    for package in server.get("packages") or []:
        if not isinstance(package, dict): continue
        identity = f"{package.get('registryType','unknown')}:{package.get('identifier','unknown')}"
        surface["packages"].add(identity)
        for group in ("runtimeArguments", "packageArguments"):
            for argument in package.get(group) or []:
                if isinstance(argument, dict): surface["arguments"].add(f"{identity}:{group}:{argument.get('name') or argument.get('valueHint') or argument.get('type')}")
        for item in package.get("environmentVariables") or []:
            if isinstance(item, dict): surface["inputs"].add(f"{item.get('name','unknown')}|required={bool(item.get('isRequired'))}|secret={bool(item.get('isSecret'))}|format={item.get('format','string')}")
        transport = package.get("transport") or {}
        for header in transport.get("headers") or []:
            if isinstance(header, dict): surface["headers"].add(str(header.get("name") or "unknown"))
    return surface


def _alert(server: str, kind: str, severity: str, evidence: Any, remediation: str) -> dict[str, Any]:
    safe_evidence = evidence if isinstance(evidence, list) else [evidence]
    identity = hashlib.sha256(_canonical([server, kind, safe_evidence]).encode()).hexdigest()[:16]
    return {"id": f"RGA-{identity}", "server": server, "kind": kind, "severity": severity,
            "evidence": safe_evidence, "remediation": remediation, "requires_manual_confirmation": True}


def diff_snapshots(previous: RegistrySnapshot | None, current: RegistrySnapshot) -> dict[str, Any]:
    before, after = _latest(previous) if previous else {}, _latest(current); alerts = []; updated = []
    added, removed = sorted(set(after) - set(before)), sorted(set(before) - set(after))
    if previous is not None:
        for name in added: alerts.append(_alert(name, "server-added", "info", after[name]["server"].get("version"), "Review publisher, repository, transports, and package provenance."))
    for name in removed: alerts.append(_alert(name, "server-removed", "medium", before[name]["server"].get("version"), "Confirm registry status and remove stale installations if appropriate."))
    for name in sorted(set(before) & set(after)):
        old, new = before[name]["server"], after[name]["server"]
        if _canonical(old) == _canonical(new) and _official(before[name]).get("status") == _official(after[name]).get("status"): continue
        updated.append({"server": name, "from_version": old.get("version"), "to_version": new.get("version")})
        if old.get("version") != new.get("version"):
            alerts.append(_alert(name, "version-changed", "info", [old.get("version"), new.get("version")], "Review the complete manifest diff before upgrading."))
        old_surface, new_surface = _surface(old), _surface(new)
        for key, kind, severity, remediation in (
            ("remotes", "remote-destination-added", "high", "Allowlist and review each new network destination."),
            ("packages", "package-install-surface-added", "high", "Verify package ownership, pinning, and provenance."),
            ("arguments", "command-argument-surface-added", "high", "Review command construction and require non-shell execution."),
            ("inputs", "configuration-input-added", "medium", "Review required, secret, and filepath inputs before deployment."),
            ("headers", "transport-header-added", "high", "Review credential handling and destination scoping for new headers.")):
            additions = sorted(new_surface[key] - old_surface[key])
            if additions: alerts.append(_alert(name, kind, severity, additions, remediation))
        if old.get("repository") != new.get("repository"):
            alerts.append(_alert(name, "repository-provenance-changed", "high", [old.get("repository"), new.get("repository")], "Verify namespace ownership and repository identity before upgrading."))
        old_rules = {item.rule_id for item in scan_server_manifest(before[name])}
        new_findings = [item for item in scan_server_manifest(after[name]) if item.rule_id not in old_rules]
        for finding in new_findings:
            alerts.append(_alert(name, "security-rule-introduced", finding.severity, finding.rule_id, finding.remediation))
        old_status, new_status = _official(before[name]).get("status"), _official(after[name]).get("status")
        if old_status != new_status:
            alerts.append(_alert(name, "registry-status-changed", "medium", [old_status, new_status], "Review the official registry status before continued use."))
    counts = Counter(item["severity"] for item in alerts)
    report: dict[str, Any] = {"format": "replayguard-mcp-registry-monitor-v1", "scope": "latest static distribution manifests only",
        "safety": "No packages installed, remote servers contacted, or MCP tools invoked.",
        "previous_snapshot_sha256": previous.response_sha256 if previous else None, "current_snapshot_sha256": current.response_sha256,
        "current_retrieved_at": current.retrieved_at, "initialized": previous is None,
        "servers_before": len(before), "servers_after": len(after), "added_servers": added, "removed_servers": removed,
        "updated_servers": updated, "alerts": sorted(alerts, key=lambda item: (-SEVERITY[item["severity"]], item["server"], item["kind"])),
        "alert_counts_by_severity": {key: counts.get(key, 0) for key in SEVERITY},
        "publication_status": "operational leads only; manually confirm before disclosure or enforcement"}
    report["report_sha256"] = hashlib.sha256(_canonical(report).encode()).hexdigest()
    return report


def render_monitor_markdown(report: dict[str, Any]) -> str:
    lines = ["# ReplayGuard MCP Registry monitor", "", f"- Retrieved: `{report['current_retrieved_at']}`",
             f"- Current snapshot: `{report['current_snapshot_sha256']}`", f"- Latest servers: **{report['servers_after']}**",
             f"- Added: **{len(report['added_servers'])}**", f"- Removed: **{len(report['removed_servers'])}**",
             f"- Updated: **{len(report['updated_servers'])}**", f"- Alerts: **{len(report['alerts'])}**", "",
             report["safety"], "Alerts require manual confirmation before disclosure or enforcement.", ""]
    if report["alerts"]:
        lines.extend(["## Alerts", "", "| Severity | Server | Change | Evidence |", "|---|---|---|---|"])
        for alert in report["alerts"]:
            evidence = ", ".join(str(item).replace("|", "\\|") for item in alert["evidence"])
            lines.append(f"| {alert['severity'].upper()} | `{alert['server']}` | {alert['kind']} | {evidence} |")
    else: lines.extend(["## Alerts", "", "None."])
    return "\n".join(lines) + "\n"


class RegistryMonitor:
    def __init__(self, history: str | Path, client: RegistryClient | None = None) -> None:
        self.history = Path(history); self.client = client or RegistryClient()

    def run(self, *, limit: int = 100, max_pages: int | None = None) -> tuple[RegistrySnapshot, dict[str, Any]]:
        self.history.mkdir(parents=True, exist_ok=True); previous = self._previous()
        current = self.client.snapshot(limit=limit, max_pages=max_pages); report = diff_snapshots(previous, current)
        self._persist(current, report)
        return current, report

    def seed(self, snapshot_path: str | Path) -> tuple[RegistrySnapshot, dict[str, Any]]:
        """Import a prior full static sweep as the first monitoring baseline."""
        if (self.history / "latest.json").exists(): raise ValueError("monitor history is already initialized")
        current = RegistrySnapshot(**json.loads(Path(snapshot_path).read_text(encoding="utf-8")))
        report = diff_snapshots(None, current); self.history.mkdir(parents=True, exist_ok=True); self._persist(current, report)
        return current, report

    def _persist(self, current: RegistrySnapshot, report: dict[str, Any]) -> None:
        prefix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        snapshot_path = self.history / f"snapshot-{prefix}-{current.response_sha256[:12]}.json"
        report_path = self.history / f"report-{prefix}-{report['report_sha256'][:12]}.json"
        snapshot_path.write_text(json.dumps(current.to_dict(), indent=2) + "\n", encoding="utf-8")
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        report_path.with_suffix(".md").write_text(render_monitor_markdown(report), encoding="utf-8")
        (self.history / "latest.json").write_text(json.dumps({"snapshot": snapshot_path.name, "report": report_path.name}, indent=2) + "\n", encoding="utf-8")

    def _previous(self) -> RegistrySnapshot | None:
        pointer = self.history / "latest.json"
        if not pointer.exists(): return None
        target = self.history / json.loads(pointer.read_text(encoding="utf-8"))["snapshot"]
        return RegistrySnapshot(**json.loads(target.read_text(encoding="utf-8")))


def monitor_loop(monitor: RegistryMonitor, *, interval_seconds: float, cycles: int | None = None,
                 on_report: Callable[[dict[str, Any]], None] | None = None, **snapshot_options) -> None:
    count = 0
    while cycles is None or count < cycles:
        _, report = monitor.run(**snapshot_options); count += 1
        if on_report: on_report(report)
        if cycles is None or count < cycles: time.sleep(interval_seconds)
