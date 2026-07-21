import json
from pathlib import Path

from replayguard.cli import main
from replayguard.mcp_registry import RegistryClient, RegistrySnapshot, aggregate_registry, scan_server_manifest


def record(name="example.test/server", *, latest=True, remotes=None, packages=None, schema=True):
    server = {"name": name, "version": "1.0.0", "remotes": remotes or [], "packages": packages or []}
    if schema: server["$schema"] = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    return {"server": server, "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active", "isLatest": latest}}}


def test_registry_pagination_contract_encodes_cursor_and_stops():
    requested = []

    def fetch(url):
        requested.append(url)
        if len(requested) == 1:
            return {"servers": [record("one.test/server")], "metadata": {"nextCursor": "one.test/server:1.0.0"}}
        return {"servers": [record("two.test/server")], "metadata": {"count": 1}}

    snapshot = RegistryClient(fetch=fetch).snapshot(limit=2)
    assert snapshot.pages == 2 and len(snapshot.records) == 2
    assert "cursor=one.test%2Fserver%3A1.0.0" in requested[1]
    assert len(snapshot.response_sha256) == 64


def test_registry_rejects_repeated_cursor():
    def fetch(_): return {"servers": [], "metadata": {"nextCursor": "same"}}
    try: RegistryClient(fetch=fetch).snapshot(); assert False
    except ValueError as exc: assert "repeated" in str(exc)


def test_static_manifest_rules_never_require_server_execution():
    bad = record(schema=False, remotes=[{"type": "streamable-http", "url": "http://user:pass@example.test/mcp"}],
                 packages=[{"registryType": "npm", "identifier": "danger", "environmentVariables": [{"name": "API_TOKEN", "value": "secret"}]}])
    findings = scan_server_manifest(bad)
    assert {item.rule_id for item in findings} == {"RGM001", "RGM002", "RGM003", "RGM004", "RGM005"}
    assert all("Manually verify" in item.reproduction[1] for item in findings)


def test_aggregate_report_excludes_individual_server_names():
    snapshot = RegistrySnapshot("https://registry.test/v0.1/servers", "2026-07-19T00:00:00Z", 1,
                                [record("private-detail.test/server")], [], "a" * 64)
    report = aggregate_registry(snapshot)
    assert report["records"] == report["unique_servers"] == report["latest_records"] == 1
    assert "private-detail" not in json.dumps(report)
    assert "No packages installed" in report["safety"]


def test_registry_cli_writes_snapshot_and_aggregate_only_report(tmp_path, monkeypatch, capsys):
    snapshot = RegistrySnapshot("https://registry.test/v0.1/servers", "2026-07-19T00:00:00Z", 1,
                                [record()], [], "b" * 64)

    class FakeClient:
        def __init__(self, endpoint, **_): self.endpoint = endpoint
        def snapshot(self, **_): return snapshot

    monkeypatch.setattr("replayguard.cli.RegistryClient", FakeClient)
    output = tmp_path / "registry"
    assert main(["mcp-scan", "--registry", "--output", str(output)]) == 0
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert (output / "snapshot.json").exists() and report["scope"] == "static distribution manifests only"
    assert "responsible disclosure" in (output / "report.md").read_text(encoding="utf-8")


def test_registry_source_is_mutually_exclusive_with_tools(tmp_path):
    manifest = tmp_path / "tools.json"; manifest.write_text("[]", encoding="utf-8")
    assert main(["mcp-scan", "--registry", "--tools", str(manifest)]) == 2
