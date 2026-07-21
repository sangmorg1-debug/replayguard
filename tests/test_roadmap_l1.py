import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from replayguard.cli import main
from replayguard.scale import SWE_BENCH_VERIFIED, ingest, iter_swe_bench, iter_tau2, swe_bench_run
from replayguard.storage import LocalStore

ROOT = Path(__file__).parents[1]
PUBLIC = ROOT / "tests/data/public"


def verified_row(instance="astropy__astropy-12907"):
    # Exact metadata shape from the pinned public dataset; content kept short for the unit path.
    return {"repo": "astropy/astropy", "instance_id": instance,
            "base_commit": "d16bfe05a744909de4b27f5875fe0d4ed41ce607",
            "problem_statement": "Modeling's separability_matrix does not compute separability correctly for nested CompoundModels",
            "hints_text": "", "patch": "diff --git a/astropy/modeling/separable.py b/astropy/modeling/separable.py",
            "test_patch": "diff --git a/astropy/modeling/tests/test_separable.py b/astropy/modeling/tests/test_separable.py",
            "FAIL_TO_PASS": '["astropy/modeling/tests/test_separable.py::test_separable"]',
            "PASS_TO_PASS": '["astropy/modeling/tests/test_separable.py::test_coord_matrix"]',
            "difficulty": "15 min - 1 hour", "environment_setup_commit": "298ccb478e6bf092953bca67a3d29dc6c35f6752"}


def test_swe_bench_adapter_preserves_verified_task_boundaries():
    run = swe_bench_run(verified_row())
    assert run.attributes["dataset_revision"] == SWE_BENCH_VERIFIED["revision"]
    assert [item.name for item in run.events] == ["github.issue", "gold.patch", "test.patch", "swe-bench.tests"]
    assert run.events[1].attributes["must_not_leak_to_candidate"] is True
    assert run.events[-1].request["fail_to_pass"]


def test_real_tau2_trajectory_directory_scales_to_thousands_of_events(tmp_path):
    started = time.perf_counter()
    report = ingest(iter_tau2(PUBLIC), LocalStore(tmp_path / "store"), dataset="tau2",
                    manifest_path=tmp_path / "manifest.json", replay_sample=3)
    assert report["runs"] == 3
    assert report["events"] == 6908 and report["logical_bytes"] > 3_000_000
    assert report["replay_sample_events"] == 6908
    assert time.perf_counter() - started < 30


def test_scale_cli_streams_jsonl_without_materializing_suite(tmp_path, capsys):
    source = tmp_path / "swe.jsonl"
    source.write_text("\n".join(json.dumps(verified_row(f"task-{index}")) for index in range(4)) + "\n", encoding="utf-8")
    store, manifest = tmp_path / "store", tmp_path / "manifest.json"
    assert main(["--store", str(store), "scale-ingest", "--format", "swe-bench-verified", "--input", str(source),
                 "--manifest", str(manifest), "--max-runs", "3", "--replay-sample", "2"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["runs"] == 3 and result["events"] == 12
    assert len(LocalStore(store).list_runs(limit=10)) == 3


def test_official_swe_bench_pin_is_exact_and_complete():
    assert SWE_BENCH_VERIFIED["revision"] == "c104f840cc67f8b6eec6f759ebc8b2693d585d4a"
    assert SWE_BENCH_VERIFIED["sha256"] == "a45b1fe4e2f0c8390b2b2938ac83e92ed5979000856808f3679c07812e9e6dcd"
    assert SWE_BENCH_VERIFIED["records"] == 500


@pytest.mark.network
@pytest.mark.skipif(os.getenv("REPLAYGUARD_VERIFY_PUBLIC_DATA") != "1", reason="explicit live network verification only")
def test_full_official_swe_bench_verified_download_and_stream(tmp_path):
    parquet = tmp_path / "verified.parquet"
    subprocess.run([sys.executable, "tools/fetch_swe_bench_verified.py", "--output", str(parquet)], check=True)
    runs = list(iter_swe_bench(parquet))
    assert len(runs) == 500 and sum(len(run.events) for run in runs) == 2000
    assert len({run.id for run in runs}) == 500
