from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from replayguard.server import create_app


def beta(tmp_path, encrypted=True):
    app = create_app(tmp_path / "beta.sqlite3", master_key=b"test-master-key-with-enough-entropy" if encrypted else None,
                     allow_bootstrap=True, max_body_bytes=20_000)
    client = TestClient(app)
    a = client.post("/v1/bootstrap", json={"name": "Alpha"}).json()
    b = client.post("/v1/bootstrap", json={"name": "Beta"}).json()
    return app, client, a, b


def headers(workspace): return {"X-ReplayGuard-Key": workspace["api_key"]}


def sample_run(trace_id="trace-a", content="alpha-canary-secret"):
    return {"id": trace_id, "name": "agent run", "status": "ok", "created_at": datetime.now(timezone.utc).isoformat(),
            "events": [{"kind": "model", "name": "answer", "response": content, "cost_usd": 0.02, "latency_ms": 25}]}


def test_authentication_roles_and_hashed_keys(tmp_path):
    app, client, a, _ = beta(tmp_path)
    assert client.get("/v1/traces").status_code == 401
    assert client.get("/v1/traces", headers={"X-ReplayGuard-Key": "bad"}).status_code == 401
    viewer = client.post("/v1/keys", headers=headers(a), json={"label": "reader", "role": "viewer"}).json()["api_key"]
    assert client.post("/v1/traces", headers={"X-ReplayGuard-Key": viewer}, json={"run": sample_run()}).status_code == 403
    assert client.get("/v1/traces", headers={"X-ReplayGuard-Key": viewer}).status_code == 200
    raw = (tmp_path / "beta.sqlite3").read_bytes()
    assert a["api_key"].encode() not in raw and viewer.encode() not in raw


def test_cross_tenant_idor_isolation_for_reads_lists_and_deletes(tmp_path):
    _, client, a, b = beta(tmp_path)
    assert client.post("/v1/traces", headers=headers(a), json={"run": sample_run()}).status_code == 201
    assert client.get("/v1/traces/trace-a", headers=headers(b)).status_code == 404
    assert client.delete("/v1/traces/trace-a", headers=headers(b)).status_code == 404
    assert client.get("/v1/traces", headers=headers(b)).json() == []
    assert "alpha-canary-secret" not in client.get("/v1/export", headers=headers(b)).text
    assert client.get("/v1/traces/trace-a", headers=headers(a)).status_code == 200


def test_metadata_default_and_encrypted_content_opt_in(tmp_path):
    _, client, a, _ = beta(tmp_path)
    metadata = client.post("/v1/traces", headers=headers(a), json={"run": sample_run("metadata")}).json()
    assert metadata["content_captured"] == 0 and metadata["content"] is None
    captured = client.post("/v1/traces", headers=headers(a),
                           json={"run": sample_run("captured"), "capture_content": True}).json()
    assert captured["content"]["events"][0]["response"] == "alpha-canary-secret"
    raw = (tmp_path / "beta.sqlite3").read_bytes()
    assert b"alpha-canary-secret" not in raw


def test_content_capture_rejected_without_encryption(tmp_path):
    _, client, a, _ = beta(tmp_path, encrypted=False)
    response = client.post("/v1/traces", headers=headers(a),
                           json={"run": sample_run(), "capture_content": True})
    assert response.status_code == 400
    assert client.post("/v1/traces", headers=headers(a), json={"run": sample_run()}).status_code == 201


def test_suites_baselines_reports_summary_export_and_audit(tmp_path):
    _, client, a, b = beta(tmp_path)
    assert client.post("/v1/suites", headers=headers(a), json={"suite": {"name": "release", "version": "1", "cases": [{"id": "1"}]}}).status_code == 201
    assert client.post("/v1/baselines", headers=headers(a), json={"name": "prod", "config": {"max_cost": 1}}).status_code == 201
    report = client.post("/v1/reports", headers=headers(a), json={"report": {"repository": "org/repo", "commit_sha": "abc", "passed": True, "cost_usd": .1, "details": "kept"}, "capture_content": True}).json()
    assert client.post("/v1/datasets", headers=headers(a), json={"name": "failures", "cases": [{"input": "real"}]}).status_code == 201
    summary = client.get("/v1/summary", headers=headers(a)).json()
    assert summary["reports"] == 1 and summary["passed_reports"] == 1 and summary["report_cost_usd"] == .1
    export = client.get("/v1/export", headers=headers(a)).json()
    assert export["workspace"]["name"] == "Alpha" and len(export["suites"]) == len(export["baselines"]) == 1
    assert export["datasets"][0]["content"]["cases"][0]["input"] == "real"
    assert client.get(f"/v1/reports/{report['id']}", headers=headers(a)).json()["content"]["details"] == "kept"
    assert client.get(f"/v1/reports/{report['id']}", headers=headers(b)).status_code == 404
    assert client.get("/v1/trends", headers=headers(a)).json()[0]["reports"] == 1
    assert client.get("/v1/suites", headers=headers(b)).json() == []
    assert len(client.get("/v1/audit", headers=headers(a)).json()) >= 3


def test_retention_and_complete_workspace_deletion(tmp_path):
    app, client, a, b = beta(tmp_path)
    client.post("/v1/traces", headers=headers(a), json={"run": sample_run()})
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    with sqlite3.connect(tmp_path / "beta.sqlite3") as db:
        db.execute("UPDATE traces SET created_at=? WHERE workspace_id=?", (old, a["workspace"]["id"]))
    assert client.put("/v1/retention", headers=headers(a), json={"days": 30}).status_code == 200
    assert client.post("/v1/retention/apply", headers=headers(a)).json()["traces_deleted"] == 1
    client.post("/v1/traces", headers=headers(a), json={"run": sample_run("delete-me")})
    assert client.delete("/v1/workspace", headers=headers(a)).status_code == 204
    assert client.get("/v1/traces", headers=headers(a)).status_code == 401
    with sqlite3.connect(tmp_path / "beta.sqlite3") as db:
        for table in ("workspaces", "api_keys", "traces", "suites", "baselines", "datasets", "reports", "audit"):
            assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE workspace_id=?" if table != "workspaces" else
                              "SELECT COUNT(*) FROM workspaces WHERE id=?", (a["workspace"]["id"],)).fetchone()[0] == 0
    assert client.get("/health").status_code == 200


def test_request_size_limit_and_security_headers(tmp_path):
    _, client, a, _ = beta(tmp_path)
    response = client.post("/v1/traces", headers=headers(a), json={"run": sample_run(content="x" * 30_000)})
    assert response.status_code == 413
    health = client.get("/health")
    assert health.headers["cache-control"] == "no-store"
    assert health.headers["x-content-type-options"] == "nosniff"
