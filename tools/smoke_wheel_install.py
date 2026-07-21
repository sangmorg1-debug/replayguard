"""Build a real wheel, install it non-editable into a clean venv, and exercise the two
CLI commands whose schema defaults are resolved relative to the installed package
(`rag aibom --schema`, `ga readiness --contract`). An editable install works even when
this path resolution is broken, so this must build and install an actual wheel."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, **kwargs)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="replayguard-wheel-smoke-") as temporary:
        temp = Path(temporary)
        dist = temp / "dist"
        run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(dist)], cwd=root)
        wheel = next(dist.glob("replayguard-*.whl"))

        environment = temp / ".venv"
        run([sys.executable, "-m", "venv", str(environment)])
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        run([str(python), "-m", "pip", "install", "--quiet", str(wheel)], stdout=subprocess.DEVNULL)

        manifest = temp / "manifest.json"
        manifest.write_text((root / "examples/aibom-manifest.json").read_text(encoding="utf-8"), encoding="utf-8")
        aibom_output = temp / "aibom.json"
        run([str(python), "-m", "replayguard.cli", "rag", "aibom",
             "--manifest", str(manifest), "--output", str(aibom_output)], cwd=temp)
        if not aibom_output.exists():
            raise SystemExit("rag aibom did not produce an output file")

        readiness_db = temp / "readiness.sqlite3"
        run([str(python), "-m", "replayguard.cli", "ga", "readiness", "--database", str(readiness_db)],
            cwd=temp)

    result = {"passed": True, "scenario": "wheel build, clean non-editable install, "
              "rag aibom and ga readiness both resolve their packaged schema/contract defaults"}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
