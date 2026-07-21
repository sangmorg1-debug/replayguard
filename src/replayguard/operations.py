from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

OPERATIONS_SCHEMA_VERSION = 1


def utcnow() -> str: return datetime.now(timezone.utc).isoformat()


class OperationsStore:
    def __init__(self, database: str | Path, monthly_request_limit: int = 100_000) -> None:
        self.database = Path(database); self.monthly_request_limit = monthly_request_limit
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.database); db.row_factory = sqlite3.Row
        try:
            yield db; db.commit()
        except Exception:
            db.rollback(); raise
        finally: db.close()

    def migrate(self) -> None:
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS usage_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT,workspace_id TEXT NOT NULL,endpoint TEXT NOT NULL,
              status_code INTEGER NOT NULL,latency_ms REAL NOT NULL,request_bytes INTEGER NOT NULL,created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS usage_workspace_time ON usage_events(workspace_id,created_at);
            CREATE TABLE IF NOT EXISTS analytics_settings(workspace_id TEXT PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS analytics_events(
              id INTEGER PRIMARY KEY AUTOINCREMENT,workspace_id TEXT NOT NULL,event TEXT NOT NULL,properties_json TEXT NOT NULL,created_at TEXT NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO schema_migrations VALUES(?,?)", (OPERATIONS_SCHEMA_VERSION, utcnow()))

    def schema_version(self) -> int:
        with self.connect() as db: return int(db.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0])

    def usage(self, workspace_id: str) -> dict[str, Any]:
        month = datetime.now(timezone.utc).strftime("%Y-%m-")
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) calls,COALESCE(SUM(request_bytes),0) bytes FROM usage_events WHERE workspace_id=? AND created_at LIKE ?",
                             (workspace_id, month + "%")).fetchone()
        return {"month": month[:7], "requests": row["calls"], "request_bytes": row["bytes"],
                "request_limit": self.monthly_request_limit, "remaining": max(0, self.monthly_request_limit - row["calls"])}

    def quota_available(self, workspace_id: str) -> bool: return self.usage(workspace_id)["remaining"] > 0

    def record_request(self, workspace_id: str, endpoint: str, status_code: int, latency_ms: float, request_bytes: int) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO usage_events(workspace_id,endpoint,status_code,latency_ms,request_bytes,created_at) VALUES(?,?,?,?,?,?)",
                       (workspace_id, endpoint, status_code, latency_ms, request_bytes, utcnow()))

    def set_analytics(self, workspace_id: str, enabled: bool) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO analytics_settings VALUES(?,?,?)", (workspace_id, int(enabled), utcnow()))

    def analytics_enabled(self, workspace_id: str) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT enabled FROM analytics_settings WHERE workspace_id=?", (workspace_id,)).fetchone()
        return bool(row and row[0])

    def record_analytics(self, workspace_id: str, event: str, properties: dict[str, Any]) -> bool:
        if not self.analytics_enabled(workspace_id): return False
        safe = {key: value for key, value in properties.items() if key in {"endpoint", "status_code", "api_version"}}
        with self.connect() as db:
            db.execute("INSERT INTO analytics_events(workspace_id,event,properties_json,created_at) VALUES(?,?,?,?)",
                       (workspace_id, event, json.dumps(safe, sort_keys=True), utcnow()))
        return True

    def slo(self, workspace_id: str | None = None) -> dict[str, Any]:
        with self.connect() as db:
            rows = db.execute("SELECT status_code,latency_ms FROM usage_events" + (" WHERE workspace_id=?" if workspace_id else ""),
                              (workspace_id,) if workspace_id else ()).fetchall()
        latencies = sorted(float(row["latency_ms"]) for row in rows)
        available = sum(int(row["status_code"]) < 500 for row in rows)
        p95 = latencies[max(0, int(len(latencies) * .95) - 1)] if latencies else None
        return {"samples": len(rows), "availability": available / len(rows) if rows else None, "p95_latency_ms": p95,
                "targets": {"availability": .999, "p95_latency_ms": 1000},
                "met": bool(rows) and available / len(rows) >= .999 and p95 <= 1000}

    def health(self) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            with self.connect() as db: integrity = db.execute("PRAGMA quick_check").fetchone()[0]
            ready = integrity == "ok" and self.schema_version() == OPERATIONS_SCHEMA_VERSION
            return {"status": "ready" if ready else "degraded", "database_integrity": integrity,
                    "schema_version": self.schema_version(), "expected_schema_version": OPERATIONS_SCHEMA_VERSION,
                    "latency_ms": (time.perf_counter() - started) * 1000}
        except sqlite3.Error as exc:
            return {"status": "unavailable", "error": type(exc).__name__}

    def backup(self, target: str | Path) -> dict[str, Any]:
        destination = Path(target).resolve(); destination.parent.mkdir(parents=True, exist_ok=True)
        if destination == self.database.resolve(): raise ValueError("backup target must differ from source database")
        source_db = sqlite3.connect(self.database); target_db = sqlite3.connect(destination)
        try: source_db.backup(target_db)
        finally: target_db.close(); source_db.close()
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        manifest = {"created_at": utcnow(), "source": str(self.database.resolve()), "backup": str(destination),
                    "sha256": digest, "schema_version": self.schema_version(), "bytes": destination.stat().st_size}
        destination.with_suffix(destination.suffix + ".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest

    @staticmethod
    def restore_copy(backup: str | Path, target: str | Path) -> dict[str, Any]:
        source, destination = Path(backup).resolve(), Path(target).resolve()
        if not source.is_file(): raise FileNotFoundError(source)
        if source == destination: raise ValueError("restore target must differ from backup")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        db = sqlite3.connect(destination)
        try: integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        finally: db.close()
        if integrity != "ok":
            destination.unlink(missing_ok=True); raise ValueError(f"restored database integrity failed: {integrity}")
        return {"restored": str(destination), "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "integrity": integrity}


def check_api_compatibility(contract: dict[str, Any], openapi: dict[str, Any]) -> dict[str, Any]:
    missing = []
    for operation in contract.get("operations", []):
        path, method = operation["path"], operation["method"].lower()
        if path not in openapi.get("paths", {}) or method not in openapi["paths"][path]:
            missing.append({"path": path, "method": method, "reason": "operation removed"})
    return {"compatible": not missing, "contract_version": contract.get("version"), "breaking_changes": missing}
