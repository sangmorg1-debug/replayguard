"""Time the N3 clean-environment install-to-first-test adoption gate."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def run(command: list[str], **kwargs) -> None:
    subprocess.run(command, check=True, **kwargs)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="replayguard-pytest-") as temporary:
        environment = Path(temporary) / ".venv"
        run([sys.executable, "-m", "venv", "--system-site-packages", str(environment)])
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([str(python), "-m", "pip", "install", "--no-deps", "-e", str(root)],
            stdout=subprocess.DEVNULL)
        run([str(python), "-m", "pytest", str(root / "examples/pytest_quickstart"), "-q"],
            cwd=temporary)
    elapsed = time.perf_counter() - started
    result = {"passed": elapsed < 600, "elapsed_seconds": round(elapsed, 3), "target_seconds": 600,
              "scenario": "clean venv, editable install, automatic pytest entry-point discovery, first exact replay test"}
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
