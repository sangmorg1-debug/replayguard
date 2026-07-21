"""Bounded, local-first OTLP/HTTP JSON tap for live agent traces."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .otel import import_traces
from .redaction import REDACTED, SENSITIVE_KEYS, Redactor
from .storage import LocalStore
from .suites import RegressionSuite


@dataclass(frozen=True)
class TapConfig:
    sample_rate: float = 0.01
    always_sample_errors: bool = True
    max_body_bytes: int = 2_000_000
    max_spans_per_request: int = 2_000
    max_traces_per_request: int = 100
    max_concurrent_requests: int = 4

    def __post_init__(self) -> None:
        if not 0 <= self.sample_rate <= 1: raise ValueError("sample_rate must be between 0 and 1")
        for name in ("max_body_bytes", "max_spans_per_request", "max_traces_per_request", "max_concurrent_requests"):
            if getattr(self, name) < 1: raise ValueError(f"{name} must be positive")


class TapMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock(); self._values = {key: 0 for key in (
            "requests", "accepted_traces", "sampled_out_traces", "accepted_spans", "rejected_spans",
            "oversize_requests", "backpressure_rejections", "authentication_failures", "invalid_requests")}

    def add(self, **values: int) -> None:
        with self._lock:
            for key, value in values.items(): self._values[key] += value

    def snapshot(self) -> dict[str, int]:
        with self._lock: return dict(self._values)


def _span_count(document: dict[str, Any]) -> int:
    return sum(len(scope.get("spans", [])) for resource in document.get("resourceSpans", document.get("resource_spans", []))
               for scope in resource.get("scopeSpans", resource.get("scope_spans", [])))


def _sanitize_attributes(value: Any) -> Any:
    """Redact OTLP key/value attribute lists before they become preserved raw spans."""
    if isinstance(value, list): return [_sanitize_attributes(item) for item in value]
    if not isinstance(value, dict): return value
    if isinstance(value.get("key"), str) and value["key"].lower() in SENSITIVE_KEYS:
        return {**value, "value": {"stringValue": REDACTED}}
    return {key: _sanitize_attributes(item) for key, item in value.items()}


def sanitize_otlp(document: dict[str, Any]) -> dict[str, Any]:
    return Redactor().redact(_sanitize_attributes(document))


def sampled(trace_id: str, rate: float) -> bool:
    if rate <= 0: return False
    if rate >= 1: return True
    value = int.from_bytes(hashlib.sha256(trace_id.encode()).digest()[:8], "big")
    return value < int(rate * (1 << 64))


class TapProcessor:
    def __init__(self, store: LocalStore, config: TapConfig | None = None, *, suite_path: str | Path | None = None,
                 metrics: TapMetrics | None = None) -> None:
        self.store, self.config, self.metrics = store, config or TapConfig(), metrics or TapMetrics()
        self.suite_path = Path(suite_path) if suite_path else None; self._suite_lock = threading.Lock()

    def process(self, document: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(document, dict) or not any(key in document for key in ("resourceSpans", "resource_spans")):
            self.metrics.add(invalid_requests=1); raise ValueError("expected an OTLP ExportTraceServiceRequest resourceSpans envelope")
        received_spans = _span_count(document)
        if received_spans > self.config.max_spans_per_request:
            self.metrics.add(rejected_spans=received_spans, invalid_requests=1)
            raise ValueError(f"span count {received_spans} exceeds limit {self.config.max_spans_per_request}")
        runs = import_traces(sanitize_otlp(document)); accepted = []; rejected_spans = 0; sampled_out = 0
        for index, run in enumerate(runs):
            if index >= self.config.max_traces_per_request:
                rejected_spans += len(run.events); continue
            keep = self.config.always_sample_errors and run.status == "error" or sampled(run.id, self.config.sample_rate)
            if keep:
                # Defense in depth: imported request/response and preserved raw spans are redacted again.
                safe = type(run).from_dict(Redactor().redact(run.to_dict()))
                self.store.save_run(safe); accepted.append(safe)
            else:
                rejected_spans += len(run.events); sampled_out += 1
        if self.suite_path and accepted: self._append_suite(accepted)
        accepted_spans = sum(len(run.events) for run in accepted)
        self.metrics.add(requests=1, accepted_traces=len(accepted), sampled_out_traces=sampled_out,
                         accepted_spans=accepted_spans, rejected_spans=rejected_spans)
        response: dict[str, Any] = {"acceptedTraces": len(accepted), "acceptedSpans": accepted_spans}
        if rejected_spans:
            response["partialSuccess"] = {"rejectedSpans": rejected_spans,
                "errorMessage": "traces were deterministically sampled out or exceeded the per-request trace limit"}
        return response

    def _append_suite(self, runs) -> None:
        with self._suite_lock:
            suite = RegressionSuite.load(self.suite_path) if self.suite_path.exists() else RegressionSuite("production-tap")
            existing = {case.source_run.get("id") for case in suite.cases}
            for run in runs:
                if run.id not in existing: suite.add_run(run, name=f"tap:{run.name}")
            self.suite_path.parent.mkdir(parents=True, exist_ok=True); suite.save(self.suite_path)


def create_tap_app(store_path: str | Path = ".verify/tap", *, config: TapConfig | None = None,
                   token: str | None = None, suite_path: str | Path | None = None) -> FastAPI:
    settings = config or TapConfig(); metrics = TapMetrics(); processor = TapProcessor(LocalStore(store_path), settings, suite_path=suite_path, metrics=metrics)
    app = FastAPI(title="ReplayGuard OTLP Tap", version="1.0.0")
    app.state.processor = processor; app.state.metrics = metrics
    app.state.capacity = threading.BoundedSemaphore(settings.max_concurrent_requests)

    @app.middleware("http")
    async def limits(request: Request, call_next):
        if request.url.path != "/v1/traces": return await call_next(request)
        length = request.headers.get("content-length")
        if length and int(length) > settings.max_body_bytes:
            metrics.add(oversize_requests=1); return JSONResponse({"detail": "request body too large"}, status_code=413)
        if not app.state.capacity.acquire(blocking=False):
            metrics.add(backpressure_rejections=1)
            return JSONResponse({"detail": "tap capacity exhausted"}, status_code=429, headers={"Retry-After": "1"})
        try: return await call_next(request)
        finally: app.state.capacity.release()

    @app.post("/v1/traces")
    async def traces(request: Request, authorization: str | None = Header(default=None)):
        if token and not hmac.compare_digest(authorization or "", f"Bearer {token}"):
            metrics.add(authentication_failures=1); raise HTTPException(401, "invalid bearer token")
        if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            raise HTTPException(415, "engineering preview accepts OTLP/HTTP JSON only")
        raw = await request.body()
        if len(raw) > settings.max_body_bytes:
            metrics.add(oversize_requests=1); raise HTTPException(413, "request body too large")
        try: document = json.loads(raw)
        except json.JSONDecodeError: metrics.add(invalid_requests=1); raise HTTPException(400, "invalid JSON")
        try:
            result = processor.process(document)
            # ExportTraceServiceResponse permits only partialSuccess; accepted counts live at /metrics.
            return {"partialSuccess": result["partialSuccess"]} if "partialSuccess" in result else {}
        except ValueError as exc: raise HTTPException(400, str(exc))

    @app.get("/healthz")
    def health(): return {"status": "ready", "mode": "engineering-preview", "otlp": "http/json"}

    @app.get("/metrics")
    def counters(): return metrics.snapshot()
    return app
