import json
from pathlib import Path

from replayguard.cli import main
from replayguard.mcp_registry import RegistrySnapshot
from replayguard.registry_monitor import RegistryMonitor, diff_snapshots, monitor_loop, render_monitor_markdown


def record(name, version, *, latest=True, status="active", remotes=None, packages=None, repository=None):
    server = {"$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
              "name": name, "description": "test", "version": version,
              "remotes": remotes or [], "packages": packages or []}
    if repository is not None: server["repository"] = repository
    return {"server": server, "_meta": {"io.modelcontextprotocol.registry/official": {
        "status": status, "isLatest": latest, "publishedAt": "2026-07-20T00:00:00Z"}}}


def snapshot(records, digest, retrieved="2026-07-20T00:00:00Z"):
    return RegistrySnapshot("https://registry.test/v0.1/servers", retrieved, 1, records, [], digest * 64)


def test_diff_compares_latest_only_and_detects_permission_escalations():
    old = snapshot([record("example.test/server", "0.9.0", latest=False),
                    record("example.test/server", "1.0.0", packages=[{"registryType":"npm","identifier":"safe","version":"1.0.0","transport":{"type":"stdio"}}])], "a")
    package = {"registryType":"npm", "identifier":"safe", "version":"2.0.0", "transport":{"type":"stdio"},
               "runtimeArguments":[{"type":"named","name":"--root","format":"filepath"}],
               "environmentVariables":[{"name":"API_TOKEN","isRequired":True,"isSecret":True}]}
    new = snapshot([record("example.test/server", "2.0.0", remotes=[{"type":"streamable-http","url":"http://new.example/mcp"}],
                           packages=[package], repository={"source":"github","url":"https://github.com/new/owner"}),
                    record("new.test/server", "1.0.0")], "b", "2026-07-21T00:00:00Z")
    report = diff_snapshots(old, new); kinds = {item["kind"] for item in report["alerts"]}
    assert report["servers_before"] == 1 and report["servers_after"] == 2
    assert {"server-added", "version-changed", "remote-destination-added", "command-argument-surface-added",
            "configuration-input-added", "repository-provenance-changed", "security-rule-introduced"} <= kinds
    assert all(item["requires_manual_confirmation"] for item in report["alerts"])
    assert "No packages installed" in report["safety"]


def test_monitor_persists_history_and_uses_previous_snapshot(tmp_path):
    values = [snapshot([record("one.test/server", "1.0.0")], "a"),
              snapshot([record("one.test/server", "2.0.0")], "b", "2026-07-21T00:00:00Z")]
    class Client:
        def snapshot(self, **_): return values.pop(0)
    monitor = RegistryMonitor(tmp_path, Client())
    _, first = monitor.run(); _, second = monitor.run()
    assert first["initialized"] is True and second["initialized"] is False
    assert first["alerts"] == []
    assert second["previous_snapshot_sha256"] == "a" * 64
    assert len(list(tmp_path.glob("snapshot-*.json"))) == 2 and (tmp_path / "latest.json").exists()


def test_monitor_can_seed_from_prior_full_static_sweep(tmp_path):
    source = tmp_path / "source.json"; source.write_text(json.dumps(snapshot([record("one.test/server", "1.0.0")], "d").to_dict()), encoding="utf-8")
    history = tmp_path / "history"; _, report = RegistryMonitor(history).seed(source)
    assert report["initialized"] is True and report["servers_after"] == 1
    try: RegistryMonitor(history).seed(source); assert False
    except ValueError as exc: assert "already initialized" in str(exc)


def test_monitor_loop_runs_bounded_cycles_without_sleep_after_last(tmp_path, monkeypatch):
    calls = []
    class Monitor:
        def run(self, **_): return None, {"alerts": [], "current_retrieved_at": "now", "report_sha256": "x"}
    monkeypatch.setattr("replayguard.registry_monitor.time.sleep", lambda value: calls.append(value))
    monitor_loop(Monitor(), interval_seconds=60, cycles=2)
    assert calls == [60]


def test_markdown_contains_local_alert_details_and_disclosure_boundary():
    report = diff_snapshots(snapshot([], "a"), snapshot([record("new.test/server", "1.0.0")], "b"))
    markdown = render_monitor_markdown(report)
    assert "new.test/server" in markdown and "manual confirmation" in markdown


def test_monitor_cli_first_run_is_non_failing(tmp_path, monkeypatch, capsys):
    current = snapshot([record("one.test/server", "1.0.0")], "c")
    class Client:
        def __init__(self, *_): pass
        def snapshot(self, **_): return current
    monkeypatch.setattr("replayguard.cli.RegistryClient", Client)
    assert main(["mcp-monitor", "--history", str(tmp_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["initialized"] is True and result["servers"] == 1
