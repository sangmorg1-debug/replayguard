from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .redaction import Redactor


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Principal:
    workspace_id: str
    key_id: str
    role: str


class WorkspaceCipher:
    def __init__(self, master_key: str | bytes | None) -> None:
        self.master_key = master_key.encode() if isinstance(master_key, str) else master_key

    @property
    def available(self) -> bool:
        return bool(self.master_key)

    def _fernet(self, workspace_id: str) -> Fernet:
        if not self.master_key:
            raise ValueError("content capture requires REPLAYGUARD_MASTER_KEY")
        raw = HKDF(algorithm=hashes.SHA256(), length=32, salt=workspace_id.encode(),
                   info=b"replayguard-workspace-content-v1").derive(self.master_key)
        return Fernet(base64.urlsafe_b64encode(raw))

    def encrypt(self, workspace_id: str, value: Any) -> bytes:
        raw = json.dumps(Redactor().redact(value), sort_keys=True, ensure_ascii=False).encode()
        return self._fernet(workspace_id).encrypt(raw)

    def decrypt(self, workspace_id: str, value: bytes | None) -> Any:
        return json.loads(self._fernet(workspace_id).decrypt(value)) if value else None


class HostedStore:
    def __init__(self, path: str | Path, master_key: str | bytes | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cipher = WorkspaceCipher(master_key or os.getenv("REPLAYGUARD_MASTER_KEY"))
        self.init()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def init(self) -> None:
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS workspaces(
              id TEXT PRIMARY KEY, name TEXT NOT NULL, retention_days INTEGER NOT NULL DEFAULT 30,
              created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS api_keys(
              id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, key_hash TEXT NOT NULL UNIQUE,
              label TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')),
              created_at TEXT NOT NULL, revoked_at TEXT,
              FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS traces(
              workspace_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL,
              created_at TEXT NOT NULL, event_count INTEGER NOT NULL, cost_usd REAL NOT NULL,
              latency_ms REAL NOT NULL, content_captured INTEGER NOT NULL, encrypted_content BLOB,
              PRIMARY KEY(workspace_id,id), FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS suites(
              workspace_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, version TEXT NOT NULL,
              case_count INTEGER NOT NULL, encrypted_content BLOB NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(workspace_id,id), FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS baselines(
              workspace_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, config_json TEXT NOT NULL,
              created_at TEXT NOT NULL, PRIMARY KEY(workspace_id,id),
              FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS datasets(
              workspace_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, case_count INTEGER NOT NULL,
              encrypted_content BLOB NOT NULL, created_at TEXT NOT NULL,
              PRIMARY KEY(workspace_id,id), FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS reports(
              workspace_id TEXT NOT NULL, id TEXT NOT NULL, repository TEXT NOT NULL, commit_sha TEXT NOT NULL,
              passed INTEGER NOT NULL, cost_usd REAL NOT NULL, created_at TEXT NOT NULL, encrypted_content BLOB,
              PRIMARY KEY(workspace_id,id), FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS audit(
              id INTEGER PRIMARY KEY AUTOINCREMENT, workspace_id TEXT NOT NULL, key_id TEXT NOT NULL,
              action TEXT NOT NULL, resource_type TEXT NOT NULL, resource_id TEXT, created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS traces_tenant_created ON traces(workspace_id,created_at DESC);
            CREATE INDEX IF NOT EXISTS reports_tenant_created ON reports(workspace_id,created_at DESC);
            """)

    def create_workspace(self, name: str) -> tuple[dict[str, Any], str]:
        workspace_id, key_id, raw_key = uuid4().hex, uuid4().hex, f"rg_{secrets.token_urlsafe(32)}"
        with self.connect() as db:
            db.execute("INSERT INTO workspaces VALUES(?,?,?,?)", (workspace_id, name, 30, now()))
            db.execute("INSERT INTO api_keys VALUES(?,?,?,?,?,?,NULL)",
                       (key_id, workspace_id, self._key_hash(raw_key), "bootstrap-owner", "owner", now()))
        return {"id": workspace_id, "name": name, "retention_days": 30}, raw_key

    def authenticate(self, raw_key: str) -> Principal | None:
        with self.connect() as db:
            row = db.execute("SELECT id,workspace_id,role FROM api_keys WHERE key_hash=? AND revoked_at IS NULL",
                             (self._key_hash(raw_key),)).fetchone()
        return Principal(row["workspace_id"], row["id"], row["role"]) if row else None

    def create_key(self, principal: Principal, label: str, role: str) -> str:
        raw, key_id = f"rg_{secrets.token_urlsafe(32)}", uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO api_keys VALUES(?,?,?,?,?,?,NULL)",
                       (key_id, principal.workspace_id, self._key_hash(raw), label, role, now()))
            self._audit(db, principal, "create", "api_key", key_id)
        return raw

    def put_trace(self, principal: Principal, run: dict[str, Any], capture_content: bool) -> dict[str, Any]:
        events = run.get("events", [])
        trace_id = str(run.get("id") or uuid4().hex)
        encrypted = self.cipher.encrypt(principal.workspace_id, run) if capture_content else None
        metadata = (principal.workspace_id, trace_id, str(run.get("name", "unnamed")), str(run.get("status", "unknown")),
                    str(run.get("created_at") or now()), len(events), sum(float(e.get("cost_usd") or 0) for e in events),
                    sum(float(e.get("latency_ms") or 0) for e in events), int(capture_content), encrypted)
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO traces VALUES(?,?,?,?,?,?,?,?,?,?)", metadata)
            self._audit(db, principal, "upsert", "trace", trace_id)
        return self.get_trace(principal, trace_id)

    def get_trace(self, principal: Principal, trace_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM traces WHERE workspace_id=? AND id=?", (principal.workspace_id, trace_id)).fetchone()
        if not row: raise KeyError(trace_id)
        item = self._row(row, drop=("workspace_id", "encrypted_content"))
        item["content"] = self.cipher.decrypt(principal.workspace_id, row["encrypted_content"]) if row["content_captured"] else None
        return item

    def list_traces(self, principal: Principal) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT id,name,status,created_at,event_count,cost_usd,latency_ms,content_captured FROM traces WHERE workspace_id=? ORDER BY created_at DESC",
                              (principal.workspace_id,)).fetchall()
        return [self._row(row) for row in rows]

    def delete_trace(self, principal: Principal, trace_id: str) -> bool:
        with self.connect() as db:
            changed = db.execute("DELETE FROM traces WHERE workspace_id=? AND id=?", (principal.workspace_id, trace_id)).rowcount
            self._audit(db, principal, "delete", "trace", trace_id)
        return bool(changed)

    def put_suite(self, principal: Principal, suite: dict[str, Any]) -> dict[str, Any]:
        suite_id = str(suite.get("id") or uuid4().hex)
        encrypted = self.cipher.encrypt(principal.workspace_id, suite)
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO suites VALUES(?,?,?,?,?,?,?)", (principal.workspace_id, suite_id,
                       str(suite.get("name", "unnamed")), str(suite.get("version", "1")), len(suite.get("cases", [])), encrypted, now()))
            self._audit(db, principal, "upsert", "suite", suite_id)
        return {"id": suite_id, "name": suite.get("name", "unnamed"), "case_count": len(suite.get("cases", []))}

    def list_suites(self, principal: Principal) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT id,name,version,case_count,created_at FROM suites WHERE workspace_id=?", (principal.workspace_id,)).fetchall()
        return [self._row(row) for row in rows]

    def put_baseline(self, principal: Principal, name: str, config: dict[str, Any]) -> dict[str, Any]:
        item_id = uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO baselines VALUES(?,?,?,?,?)", (principal.workspace_id, item_id, name,
                       json.dumps(Redactor().redact(config), sort_keys=True), now()))
            self._audit(db, principal, "create", "baseline", item_id)
        return {"id": item_id, "name": name, "config": config}

    def put_dataset(self, principal: Principal, name: str, cases: list[Any]) -> dict[str, Any]:
        item_id = uuid4().hex
        encrypted = self.cipher.encrypt(principal.workspace_id, {"name": name, "cases": cases})
        with self.connect() as db:
            db.execute("INSERT INTO datasets VALUES(?,?,?,?,?,?)", (principal.workspace_id, item_id, name, len(cases), encrypted, now()))
            self._audit(db, principal, "create", "dataset", item_id)
        return {"id": item_id, "name": name, "case_count": len(cases)}

    def list_datasets(self, principal: Principal, include_content: bool = False) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM datasets WHERE workspace_id=?", (principal.workspace_id,)).fetchall()
        items = []
        for row in rows:
            item = self._row(row, drop=("workspace_id", "encrypted_content"))
            if include_content: item["content"] = self.cipher.decrypt(principal.workspace_id, row["encrypted_content"])
            items.append(item)
        return items

    def put_report(self, principal: Principal, report: dict[str, Any], capture_content: bool) -> dict[str, Any]:
        report_id = uuid4().hex
        encrypted = self.cipher.encrypt(principal.workspace_id, report) if capture_content else None
        with self.connect() as db:
            db.execute("INSERT INTO reports VALUES(?,?,?,?,?,?,?,?)", (principal.workspace_id, report_id,
                       str(report.get("repository", "unknown")), str(report.get("commit_sha", "unknown")),
                       int(bool(report.get("passed"))), float(report.get("cost_usd", 0)), now(), encrypted))
            self._audit(db, principal, "create", "report", report_id)
        return {"id": report_id, "passed": bool(report.get("passed")), "content_captured": capture_content}

    def get_report(self, principal: Principal, report_id: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT * FROM reports WHERE workspace_id=? AND id=?", (principal.workspace_id, report_id)).fetchone()
        if not row: raise KeyError(report_id)
        item = self._row(row, drop=("workspace_id", "encrypted_content"))
        item["content"] = self.cipher.decrypt(principal.workspace_id, row["encrypted_content"]) if row["encrypted_content"] else None
        return item

    def summary(self, principal: Principal) -> dict[str, Any]:
        with self.connect() as db:
            trace = db.execute("SELECT COUNT(*) count,COALESCE(SUM(cost_usd),0) cost,COALESCE(AVG(latency_ms),0) latency FROM traces WHERE workspace_id=?", (principal.workspace_id,)).fetchone()
            report = db.execute("SELECT COUNT(*) count,COALESCE(SUM(passed),0) passed,COALESCE(SUM(cost_usd),0) cost FROM reports WHERE workspace_id=?", (principal.workspace_id,)).fetchone()
        return {"traces": trace["count"], "trace_cost_usd": trace["cost"], "average_latency_ms": trace["latency"],
                "reports": report["count"], "passed_reports": report["passed"], "report_cost_usd": report["cost"]}

    def trends(self, principal: Principal) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("""SELECT substr(created_at,1,10) day,COUNT(*) reports,SUM(passed) passed,
                               SUM(cost_usd) cost_usd FROM reports WHERE workspace_id=? GROUP BY day ORDER BY day""",
                              (principal.workspace_id,)).fetchall()
        return [self._row(row) for row in rows]

    def export(self, principal: Principal) -> dict[str, Any]:
        with self.connect() as db:
            workspace = self._row(db.execute("SELECT id,name,retention_days,created_at FROM workspaces WHERE id=?", (principal.workspace_id,)).fetchone())
            baselines = [self._row(row) for row in db.execute("SELECT id,name,config_json,created_at FROM baselines WHERE workspace_id=?", (principal.workspace_id,))]
            suite_rows = db.execute("SELECT * FROM suites WHERE workspace_id=?", (principal.workspace_id,)).fetchall()
            report_rows = db.execute("SELECT * FROM reports WHERE workspace_id=?", (principal.workspace_id,)).fetchall()
        traces = [self.get_trace(principal, item["id"]) for item in self.list_traces(principal)]
        suites = [{**self._row(row, drop=("workspace_id", "encrypted_content")),
                   "content": self.cipher.decrypt(principal.workspace_id, row["encrypted_content"])} for row in suite_rows]
        reports = [{**self._row(row, drop=("workspace_id", "encrypted_content")),
                    "content": self.cipher.decrypt(principal.workspace_id, row["encrypted_content"]) if row["encrypted_content"] else None} for row in report_rows]
        return {"workspace": workspace, "traces": traces, "suites": suites,
                "datasets": self.list_datasets(principal, include_content=True), "baselines": baselines,
                "reports": reports, "exported_at": now()}

    def set_retention(self, principal: Principal, days: int) -> None:
        with self.connect() as db:
            db.execute("UPDATE workspaces SET retention_days=? WHERE id=?", (days, principal.workspace_id))
            self._audit(db, principal, "update", "retention", str(days))

    def apply_retention(self, principal: Principal) -> dict[str, int]:
        with self.connect() as db:
            days = db.execute("SELECT retention_days FROM workspaces WHERE id=?", (principal.workspace_id,)).fetchone()[0]
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            traces = db.execute("DELETE FROM traces WHERE workspace_id=? AND created_at<?", (principal.workspace_id, cutoff)).rowcount
            reports = db.execute("DELETE FROM reports WHERE workspace_id=? AND created_at<?", (principal.workspace_id, cutoff)).rowcount
            self._audit(db, principal, "apply", "retention", None)
        return {"traces_deleted": traces, "reports_deleted": reports}

    def delete_workspace(self, principal: Principal) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM audit WHERE workspace_id=?", (principal.workspace_id,))
            db.execute("DELETE FROM workspaces WHERE id=?", (principal.workspace_id,))

    def audit(self, principal: Principal) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT action,resource_type,resource_id,created_at FROM audit WHERE workspace_id=? ORDER BY id", (principal.workspace_id,)).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _key_hash(raw: str) -> str: return hashlib.sha256(raw.encode()).hexdigest()
    @staticmethod
    def _row(row: sqlite3.Row, drop: tuple[str, ...] = ()) -> dict[str, Any]: return {key: row[key] for key in row.keys() if key not in drop}
    @staticmethod
    def _audit(db: sqlite3.Connection, principal: Principal, action: str, resource: str, resource_id: str | None) -> None:
        db.execute("INSERT INTO audit(workspace_id,key_id,action,resource_type,resource_id,created_at) VALUES(?,?,?,?,?,?)",
                   (principal.workspace_id, principal.key_id, action, resource, resource_id, now()))
