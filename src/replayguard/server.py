from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .hosted import HostedStore, Principal
from .operations import OperationsStore


class BootstrapRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class KeyRequest(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    role: Literal["owner", "editor", "viewer"]


class TraceUpload(BaseModel):
    run: dict[str, Any]
    capture_content: bool = False


class SuiteUpload(BaseModel):
    suite: dict[str, Any]


class BaselineUpload(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    config: dict[str, Any]


class ReportUpload(BaseModel):
    report: dict[str, Any]
    capture_content: bool = False


class DatasetUpload(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    cases: list[Any]


class RetentionUpdate(BaseModel):
    days: int = Field(ge=1, le=3650)


class AnalyticsUpdate(BaseModel):
    enabled: bool


def create_app(database: str | Path = ".verify/hosted.sqlite3", *, master_key: str | bytes | None = None,
               allow_bootstrap: bool = False, max_body_bytes: int = 2_000_000,
               monthly_request_limit: int = 100_000) -> FastAPI:
    app = FastAPI(title="ReplayGuard API", version="1.0.0")
    store = HostedStore(database, master_key)
    operations = OperationsStore(database, monthly_request_limit)
    app.state.store = store
    app.state.operations = operations

    @app.middleware("http")
    async def body_limit(request: Request, call_next):
        started = __import__("time").perf_counter()
        length = request.headers.get("content-length")
        if length and int(length) > max_body_bytes:
            return JSONResponse({"detail": "request body too large"}, status_code=413)
        actor = store.authenticate(request.headers.get("x-replayguard-key", "")) if request.url.path.startswith("/v1/") else None
        if actor and not operations.quota_available(actor.workspace_id):
            return JSONResponse({"detail": "monthly request limit exceeded", "usage": operations.usage(actor.workspace_id)}, status_code=429)
        response = await call_next(request)
        if actor:
            latency = (__import__("time").perf_counter() - started) * 1000
            operations.record_request(actor.workspace_id, request.url.path, response.status_code, latency, int(length or 0))
            operations.record_analytics(actor.workspace_id, "api_request", {"endpoint": request.url.path,
                                        "status_code": response.status_code, "api_version": "1.0.0"})
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["ReplayGuard-API-Version"] = "1.0.0"
        return response

    def principal(x_replayguard_key: str | None = Header(default=None)) -> Principal:
        if not x_replayguard_key:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key required")
        value = store.authenticate(x_replayguard_key)
        if not value:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid API key")
        return value

    def require(*roles: str):
        def dependency(value: Principal = Depends(principal)) -> Principal:
            if value.role not in roles:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
            return value
        return dependency

    def encrypted_content_required() -> None:
        if not store.cipher.available:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "content storage is disabled until an encryption key is configured")

    @app.get("/livez")
    def livez(): return {"status": "alive", "api_version": "1.0.0"}

    @app.get("/readyz")
    def readyz():
        value = operations.health()
        if value["status"] != "ready": raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, value)
        return {**value, "content_encryption": store.cipher.available, "api_version": "1.0.0"}

    @app.get("/health")
    def health(): return {**operations.health(), "content_encryption": store.cipher.available, "api_version": "1.0.0"}

    @app.post("/v1/bootstrap", status_code=201)
    def bootstrap(body: BootstrapRequest):
        if not allow_bootstrap:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
        workspace, key = store.create_workspace(body.name)
        return {"workspace": workspace, "api_key": key, "warning": "the API key is shown once"}

    @app.post("/v1/keys", status_code=201)
    def create_key(body: KeyRequest, actor: Principal = Depends(require("owner"))):
        return {"api_key": store.create_key(actor, body.label, body.role), "warning": "the API key is shown once"}

    @app.post("/v1/traces", status_code=201)
    def put_trace(body: TraceUpload, actor: Principal = Depends(require("owner", "editor"))):
        if body.capture_content: encrypted_content_required()
        return store.put_trace(actor, body.run, body.capture_content)

    @app.get("/v1/traces")
    def traces(actor: Principal = Depends(principal)): return store.list_traces(actor)

    @app.get("/v1/traces/{trace_id}")
    def trace(trace_id: str, actor: Principal = Depends(principal)):
        try: return store.get_trace(actor, trace_id)
        except KeyError: raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    @app.delete("/v1/traces/{trace_id}", status_code=204)
    def delete_trace(trace_id: str, actor: Principal = Depends(require("owner", "editor"))):
        if not store.delete_trace(actor, trace_id): raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    @app.post("/v1/suites", status_code=201)
    def put_suite(body: SuiteUpload, actor: Principal = Depends(require("owner", "editor"))):
        encrypted_content_required()
        return store.put_suite(actor, body.suite)

    @app.get("/v1/suites")
    def suites(actor: Principal = Depends(principal)): return store.list_suites(actor)

    @app.post("/v1/baselines", status_code=201)
    def put_baseline(body: BaselineUpload, actor: Principal = Depends(require("owner", "editor"))):
        return store.put_baseline(actor, body.name, body.config)

    @app.post("/v1/reports", status_code=201)
    def put_report(body: ReportUpload, actor: Principal = Depends(require("owner", "editor"))):
        if body.capture_content: encrypted_content_required()
        return store.put_report(actor, body.report, body.capture_content)

    @app.get("/v1/reports/{report_id}")
    def report(report_id: str, actor: Principal = Depends(principal)):
        try: return store.get_report(actor, report_id)
        except KeyError: raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")

    @app.post("/v1/datasets", status_code=201)
    def put_dataset(body: DatasetUpload, actor: Principal = Depends(require("owner", "editor"))):
        encrypted_content_required()
        return store.put_dataset(actor, body.name, body.cases)

    @app.get("/v1/datasets")
    def datasets(actor: Principal = Depends(principal)): return store.list_datasets(actor)

    @app.get("/v1/summary")
    def summary(actor: Principal = Depends(principal)): return store.summary(actor)

    @app.get("/v1/trends")
    def trends(actor: Principal = Depends(principal)): return store.trends(actor)

    @app.get("/v1/export")
    def export(actor: Principal = Depends(principal)): return store.export(actor)

    @app.put("/v1/retention")
    def set_retention(body: RetentionUpdate, actor: Principal = Depends(require("owner"))):
        store.set_retention(actor, body.days)
        return {"retention_days": body.days}

    @app.post("/v1/retention/apply")
    def apply_retention(actor: Principal = Depends(require("owner"))): return store.apply_retention(actor)

    @app.get("/v1/audit")
    def audit(actor: Principal = Depends(require("owner"))): return store.audit(actor)

    @app.get("/v1/usage")
    def usage(actor: Principal = Depends(principal)): return operations.usage(actor.workspace_id)

    @app.get("/v1/slo")
    def slo(actor: Principal = Depends(require("owner"))): return operations.slo(actor.workspace_id)

    @app.put("/v1/analytics")
    def analytics(body: AnalyticsUpdate, actor: Principal = Depends(require("owner"))):
        operations.set_analytics(actor.workspace_id, body.enabled)
        return {"enabled": body.enabled, "content_collected": False}

    @app.delete("/v1/workspace", status_code=204)
    def delete_workspace(actor: Principal = Depends(require("owner"))): store.delete_workspace(actor)

    return app
