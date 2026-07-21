"""Run a disposable GA migration, load, backup, restore, and compatibility drill."""
import json
import tempfile
import time
from pathlib import Path

from replayguard.operations import OperationsStore, check_api_compatibility
from replayguard.server import create_app

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="replayguard-ga-") as directory:
        root = Path(directory); database = root / "live.sqlite3"; backup = root / "backup.sqlite3"; restored = root / "restored.sqlite3"
        operations = OperationsStore(database)
        started = time.perf_counter()
        for index in range(1000): operations.record_request("drill", "/v1/traces", 200, index % 100, 100)
        backup_manifest = operations.backup(backup)
        restore = OperationsStore.restore_copy(backup, restored)
        contract = json.loads((ROOT / "schemas/public-api-v1.contract.json").read_text(encoding="utf-8"))
        compatibility = check_api_compatibility(contract, create_app(restored).openapi())
        print(json.dumps({"migration_version": operations.schema_version(), "api_compatible": compatibility["compatible"],
                          "slo": operations.slo("drill"), "backup_bytes": backup_manifest["bytes"],
                          "restore_integrity": restore["integrity"], "drill_seconds": time.perf_counter() - started}, indent=2))


if __name__ == "__main__": main()
