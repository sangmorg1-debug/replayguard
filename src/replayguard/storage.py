from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from .schema import Run


class LocalStore:
    def __init__(self, root: str | Path = ".verify") -> None:
        self.root = Path(root)
        self.blobs = self.root / "blobs"
        self.db_path = self.root / "index.sqlite3"

    def init(self) -> None:
        self.blobs.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL,
                    status TEXT NOT NULL, schema_version TEXT NOT NULL, blob_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS runs_created ON runs(created_at DESC);
            """)

    def put_blob(self, value: Any) -> str:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        digest = hashlib.sha256(raw).hexdigest()
        path = self.blobs / digest[:2] / f"{digest}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temp = path.with_suffix(f".{os.getpid()}.tmp")
            temp.write_bytes(raw)
            temp.replace(path)
        return digest

    def get_blob(self, digest: str) -> Any:
        return json.loads((self.blobs / digest[:2] / f"{digest}.json").read_text(encoding="utf-8"))

    def save_run(self, run: Run) -> str:
        self.init()
        digest = self.put_blob(run.to_dict())
        with sqlite3.connect(self.db_path) as db:
            db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                       (run.id, run.name, run.created_at, run.status, run.schema_version, digest))
        return digest

    def load_run(self, run_id: str) -> Run:
        with sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT blob_hash FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            raise KeyError(f"unknown run: {run_id}")
        return Run.from_dict(self.get_blob(row[0]))

    def list_runs(self, limit: int = 20) -> list[dict[str, str]]:
        self.init()
        with sqlite3.connect(self.db_path) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                "SELECT id,name,created_at,status,schema_version FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))]

    def prune(self, keep: int) -> int:
        self.init()
        with sqlite3.connect(self.db_path) as db:
            ids = [row[0] for row in db.execute("SELECT id FROM runs ORDER BY created_at DESC LIMIT -1 OFFSET ?", (keep,))]
            db.executemany("DELETE FROM runs WHERE id = ?", ((item,) for item in ids))
        return len(ids)

