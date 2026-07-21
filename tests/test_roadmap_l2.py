import json
from pathlib import Path

from fastapi.testclient import TestClient

from replayguard.cli import main
from replayguard.otel import export_otlp, import_traces
from replayguard.storage import LocalStore
from replayguard.suites import RegressionSuite
from replayguard.tap import TapConfig, TapProcessor, create_tap_app, sampled

ROOT = Path(__file__).parents[1]
PUBLIC = ROOT / "tests/data/public/openinference_otel_spans.json"


def envelope(trace="1" * 32, *, status=1, secret=False):
    attributes = [{"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}}]
    if secret: attributes.append({"key": "authorization", "value": {"stringValue": "Bearer abcdefghijklmnop"}})
    return {"resourceSpans": [{"resource": {"attributes": []}, "scopeSpans": [{"scope": {"name": "test"}, "spans": [{
        "traceId": trace, "spanId": "2" * 16, "name": "agent.chat", "startTimeUnixNano": "1000000000",
        "endTimeUnixNano": "2000000000", "attributes": attributes, "status": {"code": status}}]}]}]}


def test_real_openinference_spans_are_sampled_redacted_stored_and_added_to_suite(tmp_path):
    flat = json.loads(PUBLIC.read_text(encoding="utf-8"))
    document = export_otlp(import_traces(flat))
    first = document["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    first.setdefault("attributes", []).append({"key": "authorization", "value": {"stringValue": "Bearer abcdefghijklmnop"}})
    store, suite = LocalStore(tmp_path / "store"), tmp_path / "tap-suite.json"
    result = TapProcessor(store, TapConfig(sample_rate=1), suite_path=suite).process(document)
    assert result["acceptedTraces"] > 0 and result["acceptedSpans"] == len(flat)
    assert len(store.list_runs(limit=100)) == result["acceptedTraces"]
    assert len(RegressionSuite.load(suite).cases) == result["acceptedTraces"]
    assert b"abcdefghijklmnop" not in b"".join(path.read_bytes() for path in (tmp_path / "store/blobs").rglob("*.json"))


def test_sampling_is_deterministic_and_errors_override_zero_rate(tmp_path):
    decisions = [sampled("stable-trace", .37) for _ in range(20)]
    assert len(set(decisions)) == 1
    processor = TapProcessor(LocalStore(tmp_path / "store"), TapConfig(sample_rate=0, always_sample_errors=True))
    dropped = processor.process(envelope("a" * 32))
    accepted = processor.process(envelope("b" * 32, status=2))
    assert dropped["acceptedTraces"] == 0 and dropped["partialSuccess"]["rejectedSpans"] == 1
    assert accepted["acceptedTraces"] == 1


def test_otlp_http_json_contract_auth_limits_and_metrics(tmp_path):
    app = create_tap_app(tmp_path / "store", config=TapConfig(sample_rate=1, max_body_bytes=2000,
                         max_spans_per_request=2, max_concurrent_requests=1), token="tap-secret")
    client = TestClient(app)
    assert client.post("/v1/traces", json=envelope()).status_code == 401
    headers = {"Authorization": "Bearer tap-secret"}
    response = client.post("/v1/traces", json=envelope(secret=True), headers=headers)
    assert response.status_code == 200 and response.json() == {}
    assert client.post("/v1/traces", content=b"x", headers={**headers, "Content-Type": "application/x-protobuf"}).status_code == 415
    assert client.post("/v1/traces", content=b"{" + b"x" * 3000, headers={**headers, "Content-Type": "application/json"}).status_code == 413
    metrics = client.get("/metrics").json()
    assert metrics["accepted_traces"] == 1 and metrics["accepted_spans"] == 1


def test_backpressure_returns_retry_after(tmp_path):
    app = create_tap_app(tmp_path / "store", config=TapConfig(sample_rate=1, max_concurrent_requests=1))
    client = TestClient(app); assert app.state.capacity.acquire(blocking=False)
    try:
        response = client.post("/v1/traces", json=envelope())
        assert response.status_code == 429 and response.headers["retry-after"] == "1"
    finally: app.state.capacity.release()


def test_span_limit_rejects_before_storage(tmp_path):
    document = envelope(); span = document["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    document["resourceSpans"][0]["scopeSpans"][0]["spans"].append({**span, "spanId": "3" * 16})
    processor = TapProcessor(LocalStore(tmp_path / "store"), TapConfig(sample_rate=1, max_spans_per_request=1))
    try: processor.process(document); assert False
    except ValueError as exc: assert "exceeds limit" in str(exc)
    assert LocalStore(tmp_path / "store").list_runs() == []


def test_non_loopback_cli_requires_authentication(capsys):
    assert main(["tap", "--host", "0.0.0.0"]) == 2
    assert "bearer --token" in capsys.readouterr().err
