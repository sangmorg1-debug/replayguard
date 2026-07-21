import hashlib
import json
from pathlib import Path

from replayguard.cli import main
from replayguard.compliance import OBLIGATIONS, SOURCES, build_pack


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_pack_generates_from_empty_workspace_and_keeps_process_boundaries(tmp_path):
    pack = build_pack(tmp_path, tmp_path / ".verify/compliance-pack")
    assert pack["summary"]["artifacts"] == 0
    assert pack["summary"]["process"] > 0
    assert pack["summary"]["missing_evidence"] > 0
    assert "not legal advice" in pack["disclaimer"]
    assert (tmp_path / ".verify/compliance-pack/pack.json").exists()


def test_pack_discovers_copies_and_hashes_real_replayguard_artifacts(tmp_path):
    verify = tmp_path / ".verify"
    write_json(verify / "report/evidence.json", {"format": "replayguard-evidence-v1", "summary": {"total": 1}})
    write_json(verify / "aibom.json", {"bomFormat": "ReplayGuard-AIBOM", "components": []})
    write_json(verify / "rag-report.json", {"summary": {}, "cases": [{"provenance": {"sha256": "a"}}]})
    write_json(verify / "threat/coverage.json", {"format": "replayguard-threat-coverage-v1"})
    (verify / "gateway.sqlite3").write_bytes(b"SQLite format 3\0test")
    pack = build_pack(tmp_path, verify / "compliance-pack")
    assert {item["type"] for item in pack["artifacts"]} == {"ci-evidence", "aibom", "rag-report", "threat-coverage", "gateway-audit"}
    for item in pack["artifacts"]:
        target = verify / "compliance-pack" / item["packaged"]
        assert target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"]
    assert any(row["reference"] == "Article 53(1)(a)" and row["support"] == "evidence" for row in pack["coverage"])


def test_profiles_filter_obligations_without_claiming_process_completion(tmp_path):
    provider = build_pack(tmp_path, tmp_path / "provider", profile="provider")
    assert provider["coverage"] and {row["profile"] for row in provider["coverage"]} == {"provider"}
    assert all(row["support"] == "process" and not row["evidence"] for row in provider["coverage"])


def test_every_obligation_has_a_source_reference_and_explicit_automation_class():
    assert {item[0].split("(")[0].strip() for item in OBLIGATIONS} <= {"Article 50", "Article 53", "Article 55"}
    assert {item[3] for item in OBLIGATIONS} <= {"evidence", "partial", "process"}
    assert SOURCES["regulation"]["identifier"] == "CELEX:32024R1689"
    assert SOURCES["article_50_guidelines"]["identifier"].endswith("2026-07-20")


def test_compliance_pack_cli(tmp_path, capsys):
    output = tmp_path / "pack"
    assert main(["compliance-pack", "--workspace", str(tmp_path), "--output", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["obligations"] == len(OBLIGATIONS)
    assert Path(result["pack"]).exists() and Path(result["coverage"]).exists()
