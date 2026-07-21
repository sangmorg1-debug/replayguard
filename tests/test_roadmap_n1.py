import json
import hashlib
import importlib.util
from pathlib import Path

from replayguard.cli import main
from replayguard.otel import RESERVED, coverage, export_otlp, import_traces, normalized
from replayguard.replay import ReplayMode, Replayer, assert_side_effect_free
from replayguard.schema import EventKind
from replayguard.storage import LocalStore

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "tests/data/public/openinference_otel_spans.json"


def load_benchmark_module():
    spec = importlib.util.spec_from_file_location("benchmark_otel", ROOT / "tools/benchmark_otel.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def load_fetch_module():
    spec = importlib.util.spec_from_file_location("fetch_trail_hf", ROOT / "tools/fetch_trail_hf.py")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def otlp_document():
    return {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "agent"}}]},
        "scopeSpans": [{"scope": {"name": "instrumentor", "version": "1.2"}, "spans": [{
            "traceId": "a" * 32, "spanId": "b" * 16, "parentSpanId": "c" * 16, "traceState": "vendor=x", "flags": 1,
            "name": "chat gpt", "kind": "SPAN_KIND_CLIENT", "startTimeUnixNano": "1700000000123456789",
            "endTimeUnixNano": "1700000001123456789", "status": {"code": "STATUS_CODE_OK"},
            "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
                           {"key": "gen_ai.usage.input_tokens", "value": {"intValue": "12"}},
                           {"key": "vendor.unknown", "value": {"kvlistValue": {"values": [{"key": "x", "value": {"arrayValue": {"values": [{"boolValue": True}, {"doubleValue": 1.5}]}}}]}}}],
            "events": [{"timeUnixNano": "1700000000223456789", "name": "prompt", "attributes": []}],
            "links": [{"traceId": "d" * 32, "spanId": "e" * 16, "attributes": []}]
        }]}]}]}


def test_otlp_import_maps_canonical_fields_and_opaque_metadata():
    run = import_traces(otlp_document())[0]; event = run.events[0]
    assert run.id == "a" * 32 and event.id == "b" * 16 and event.parent_id == "c" * 16
    assert event.kind == EventKind.MODEL and event.usage == {"input_tokens": 12}
    assert event.attributes["vendor.unknown"] == {"x": [True, 1.5]}
    assert event.attributes[RESERVED]["adapter_version"] == "otel-1.0.0"


def test_otlp_semantic_roundtrip_preserves_nanos_events_links_resource_scope():
    source = otlp_document(); exported = export_otlp(import_traces(source))
    assert normalized(source) == normalized(exported)
    span = exported["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["startTimeUnixNano"] == "1700000000123456789"
    assert span["events"] == source["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["events"]


def test_canonical_edit_is_reflected_on_export():
    run = import_traces(otlp_document())[0]
    run.events[0].name = "changed"
    assert export_otlp(run)["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["name"] == "changed"


def test_exact_replay_of_imported_trace_has_no_live_side_effects():
    run = import_traces(otlp_document())[0]
    result = Replayer().replay(run, mode=ReplayMode.EXACT)
    assert assert_side_effect_free(run, result) and result.live_calls == 0


def test_real_pinned_openinference_spans_all_import_and_roundtrip():
    document = json.loads(PUBLIC.read_text(encoding="utf-8"))
    runs = import_traces(document); exported = export_otlp(runs)
    assert len(document) == sum(len(item.events) for item in runs) == 10
    assert normalized(document) == normalized(exported)
    assert all(item.events for item in runs)


def test_real_attribute_coverage_reports_genai_and_other():
    report = coverage(import_traces(json.loads(PUBLIC.read_text(encoding="utf-8"))))
    assert report["spans"] == 10 and report["attribute_occurrences"]["gen_ai"] > 0
    assert report["conventions"]["otlp"] == "1.10.0"


def test_cli_import_export_coverage_and_roundtrip(tmp_path):
    store = tmp_path / "store"; output = tmp_path / "export.json"
    assert main(["--store", str(store), "otel", "roundtrip", str(PUBLIC), "--output", str(output)]) == 0
    assert main(["--store", str(store), "otel", "coverage", str(PUBLIC)]) == 0
    assert main(["--store", str(store), "otel", "import", str(PUBLIC)]) == 0
    run_ids = [item["id"] for item in LocalStore(store).list_runs(limit=20)]
    assert main(["--store", str(store), "otel", "export", *run_ids, "--output", str(output)]) == 0
    assert output.exists()


def content_bearing_document():
    return {"resourceSpans": [{"resource": {}, "scopeSpans": [{"scope": {}, "spans": [{
        "traceId": "f" * 32, "spanId": "1" * 16, "name": "chat", "startTimeUnixNano": "1700000000000000000",
        "status": {"code": "STATUS_CODE_OK"},
        "attributes": [{"key": "input.value", "value": {"stringValue": "What is my account balance, my token is sk-abcdefghijklmnopqrstuvwxyz?"}},
                       {"key": "output.value", "value": {"stringValue": "Your balance is $42."}}],
        "events": [], "links": []}]}]}]}


def test_cli_otel_import_does_not_persist_content_by_default(tmp_path):
    """verify otel import must not bypass the project's content-off-by-default privacy default:
    real prompts/responses from a live trace export must not land unredacted in local storage
    unless the caller explicitly opts in with --capture-content, matching `verify record`."""
    store = tmp_path / "store"
    document = tmp_path / "trace.json"
    document.write_text(json.dumps(content_bearing_document()), encoding="utf-8")
    assert main(["--store", str(store), "otel", "import", str(document)]) == 0
    run_id = LocalStore(store).list_runs(limit=1)[0]["id"]
    loaded = LocalStore(store).load_run(run_id)
    blob = json.dumps(loaded.to_dict())
    assert "account balance" not in blob
    assert "Your balance is $42" not in blob
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in blob
    assert loaded.events[0].request_hash and loaded.events[0].response_hash


def test_cli_otel_import_capture_content_preserves_full_fidelity(tmp_path):
    store = tmp_path / "store"
    document = tmp_path / "trace.json"
    document.write_text(json.dumps(content_bearing_document()), encoding="utf-8")
    assert main(["--store", str(store), "otel", "import", str(document), "--capture-content"]) == 0
    run_id = LocalStore(store).list_runs(limit=1)[0]["id"]
    loaded = LocalStore(store).load_run(run_id)
    assert loaded.events[0].response == "Your balance is $42."
    # Even with content captured, known secret patterns are still redacted, same as `verify record`.
    assert "sk-abcdefghijklmnopqrstuvwxyz" not in json.dumps(loaded.to_dict())


def test_invalid_trace_shape_rejected():
    try: import_traces({"logs": []}); assert False
    except ValueError as exc: assert "expected OTLP" in str(exc)


def test_full_trail_corpus_verifier_checks_pins_and_roundtrip(tmp_path):
    root = tmp_path / "trail"; trace = root / "traces/GAIA/real.json"
    trace.parent.mkdir(parents=True); body = json.dumps({"trace_id": "real", "spans": [{
        "trace_id": "real", "span_id": "span", "span_name": "agent", "timestamp": "2025-01-01T00:00:00Z",
        "duration": "PT0.1S", "span_attributes": {"gen_ai.operation.name": "invoke_agent"}
    }]}).encode()
    trace.write_bytes(body)
    manifest = {"repository": "patronus-ai/trail-benchmark", "revision": "pinned", "records": [{
        "split": "GAIA", "trace_id": "real", "trace_path": "traces/GAIA/real.json",
        "trace_sha256": hashlib.sha256(body).hexdigest()
    }]}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    report = load_benchmark_module().measure_trail_corpus(root)
    assert report["trace_files"] == report["coverage"]["runs"] == report["coverage"]["spans"] == 1
    assert report["semantic_roundtrip_failures"] == 0


def test_full_trail_corpus_verifier_refuses_checksum_drift(tmp_path):
    root = tmp_path / "trail"; trace = root / "trace.json"; root.mkdir(); trace.write_text('{"spans": []}')
    (root / "manifest.json").write_text(json.dumps({"repository": "x", "revision": "y", "records": [{
        "split": "GAIA", "trace_id": "x", "trace_path": "trace.json", "trace_sha256": "0" * 64
    }]}))
    try: load_benchmark_module().measure_trail_corpus(root); assert False
    except ValueError as exc: assert "checksum mismatch" in str(exc)


def test_gated_trail_manifest_requires_annotation_pairing(tmp_path):
    (tmp_path / "GAIA").mkdir(); (tmp_path / "SWE Bench").mkdir()
    (tmp_path / "GAIA/x.json").write_text("{}")
    try: load_fetch_module().build_manifest(tmp_path); assert False
    except ValueError as exc: assert "missing TRAIL annotation" in str(exc)
