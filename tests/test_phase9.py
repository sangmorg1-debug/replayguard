import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from replayguard.cli import main
from replayguard.operations import OPERATIONS_SCHEMA_VERSION, OperationsStore, check_api_compatibility
from replayguard.server import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_migrations_are_idempotent_and_versioned(tmp_path):
    path = tmp_path / "hosted.sqlite3"
    first = OperationsStore(path); second = OperationsStore(path)
    assert first.schema_version() == second.schema_version() == OPERATIONS_SCHEMA_VERSION
    with first.connect() as db: assert db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1


def test_usage_quota_and_attribution(tmp_path):
    ops = OperationsStore(tmp_path / "db.sqlite3", monthly_request_limit=2)
    assert ops.quota_available("w")
    ops.record_request("w", "/v1/traces", 200, 10, 100)
    ops.record_request("w", "/v1/traces", 500, 30, 200)
    usage = ops.usage("w")
    assert usage["requests"] == 2 and usage["request_bytes"] == 300 and usage["remaining"] == 0
    assert not ops.quota_available("w")


def test_analytics_is_opt_in_and_metadata_only(tmp_path):
    ops = OperationsStore(tmp_path / "db.sqlite3")
    assert not ops.record_analytics("w", "api_request", {"endpoint": "/x", "secret": "never-store"})
    ops.set_analytics("w", True)
    assert ops.record_analytics("w", "api_request", {"endpoint": "/x", "secret": "never-store"})
    with ops.connect() as db: body = db.execute("SELECT properties_json FROM analytics_events").fetchone()[0]
    assert "secret" not in body and "/x" in body


def test_slo_calculates_availability_and_p95(tmp_path):
    ops = OperationsStore(tmp_path / "db.sqlite3")
    for index in range(1000): ops.record_request("w", "/x", 200, index % 100, 0)
    report = ops.slo("w")
    assert report["availability"] == 1 and report["p95_latency_ms"] == 94 and report["met"]


def test_backup_restore_and_integrity(tmp_path):
    database = tmp_path / "source.sqlite3"; backup = tmp_path / "backups/one.sqlite3"; restored = tmp_path / "restored.sqlite3"
    ops = OperationsStore(database)
    with ops.connect() as db: db.execute("CREATE TABLE evidence(value TEXT)"); db.execute("INSERT INTO evidence VALUES('kept')")
    manifest = ops.backup(backup)
    result = OperationsStore.restore_copy(backup, restored)
    assert manifest["schema_version"] == OPERATIONS_SCHEMA_VERSION and result["integrity"] == "ok"
    with sqlite3.connect(restored) as db: assert db.execute("SELECT value FROM evidence").fetchone()[0] == "kept"


def test_backup_refuses_source_and_restore_refuses_backup_target(tmp_path):
    path = tmp_path / "db.sqlite3"; ops = OperationsStore(path)
    try: ops.backup(path); assert False
    except ValueError: pass
    try: OperationsStore.restore_copy(path, path); assert False
    except ValueError: pass


def test_health_checks_integrity_and_schema(tmp_path):
    health = OperationsStore(tmp_path / "db.sqlite3").health()
    assert health["status"] == "ready" and health["database_integrity"] == "ok"


def test_public_api_contract_is_backward_compatible(tmp_path):
    app = create_app(tmp_path / "db.sqlite3")
    contract = json.loads((ROOT / "schemas/public-api-v1.contract.json").read_text())
    assert check_api_compatibility(contract, app.openapi())["compatible"]
    app.openapi()["paths"].pop("/v1/traces")
    assert not check_api_compatibility(contract, app.openapi())["compatible"]


def test_ga_health_version_headers_usage_and_analytics(tmp_path):
    app = create_app(tmp_path / "db.sqlite3", master_key=b"x" * 32, allow_bootstrap=True, monthly_request_limit=20)
    client = TestClient(app)
    assert client.get("/livez").json()["api_version"] == "1.0.0"
    assert client.get("/readyz").status_code == 200
    bootstrap = client.post("/v1/bootstrap", json={"name": "team"}).json(); headers = {"X-ReplayGuard-Key": bootstrap["api_key"]}
    response = client.get("/v1/usage", headers=headers)
    assert response.status_code == 200 and response.headers["ReplayGuard-API-Version"] == "1.0.0"
    assert client.put("/v1/analytics", headers=headers, json={"enabled": True}).json()["content_collected"] is False
    assert client.get("/v1/slo", headers=headers).status_code == 200


def test_api_enforces_monthly_limit(tmp_path):
    app = create_app(tmp_path / "db.sqlite3", allow_bootstrap=True, monthly_request_limit=1)
    client = TestClient(app)
    key = client.post("/v1/bootstrap", json={"name": "team"}).json()["api_key"]
    headers = {"X-ReplayGuard-Key": key}
    assert client.get("/v1/usage", headers=headers).status_code == 200
    assert client.get("/v1/usage", headers=headers).status_code == 429


def test_ga_cli_backup_restore_and_readiness(tmp_path):
    database, backup, restored = tmp_path / "db.sqlite3", tmp_path / "backup.sqlite3", tmp_path / "restored.sqlite3"
    OperationsStore(database)
    assert main(["ga", "backup", "--database", str(database), "--output", str(backup)]) == 0
    assert main(["ga", "restore-copy", "--backup", str(backup), "--output", str(restored)]) == 0
    assert main(["ga", "readiness", "--database", str(database)]) == 0
