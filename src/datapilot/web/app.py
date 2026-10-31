"""Loopback-only, versioned host API. No HTTP route initializes or migrates a database."""

import asyncio
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, File, Form, Header, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import ImportResult
from datapilot.db.management import management_url
from datapilot.ingestion.contracts import ParseFailure, ParseOptions
from datapilot.persistence.session import run_async
from datapilot.semantics.contracts import MetricVersion, SemanticDraft, SemanticVersion
from datapilot.web.body_limit import BodyLimit
from datapilot.web.chat_routes import register_chat_routes
from datapilot.web.config import ROOT, load_policy
from datapilot.web.contracts import (
    Acknowledgement,
    CorporaView,
    CreateTask,
    DatasetView,
    DatasetViews,
    DocumentIngested,
    ErrorResponse,
    HealthView,
    ImportUpload,
    MetricFact,
    MetricReview,
    ReportView,
    SchemaReview,
    SemanticReview,
    SessionView,
    TaskAction,
    TaskIDs,
    TaskView,
    TraceView,
    UploadView,
)
from datapilot.web.service import ProductService, preview, public_schema, report_view
from datapilot.web.store import WebStore, deny
from datapilot.web.worker import Dispatcher


def create_app(*, policy=None, settings=None, dispatch=True, policy_file=None):
    policy_file = Path(policy_file or ROOT / "artifacts/web/host.json")
    policy = policy or load_policy(policy_file)
    settings = settings or Settings()
    store = WebStore(management_url("web"), policy)
    service = ProductService(settings, store)
    service.bind_host_settings()
    store.settings_provider = lambda: service.settings

    @asynccontextmanager
    async def lifespan(app):
        dispatcher = Dispatcher(store, policy_file) if dispatch else None
        job = asyncio.create_task(dispatcher.run()) if dispatcher else None
        yield
        if dispatcher:
            await dispatcher.close()
            job.cancel()
            with suppress(asyncio.CancelledError):
                await job
        store.close()

    app = FastAPI(
        responses={code: {"model": ErrorResponse} for code in (403, 409, 413, 422, 500)},
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        },
        title="DataPilot Pro local API",
        version="1.0",
        lifespan=lifespan,
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        redoc_url=None,
    )
    app.state.store, app.state.service = store, service
    app.add_middleware(BodyLimit)
    register_chat_routes(app, service)

    def openapi():
        if app.openapi_schema is None:
            spec = get_openapi(title=app.title, version=app.version, routes=app.routes)
            spec["components"]["securitySchemes"] = {
                "HostSession": {"type": "apiKey", "in": "cookie", "name": "datapilot_session"},
                "CSRF": {"type": "apiKey", "in": "header", "name": "X-CSRF-Token"},
                "HostBootstrap": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-DataPilot-Host-Key",
                    "description": "Host/UI server only. Never expose to browser/model.",
                },
            }
            for path, operations in spec["paths"].items():
                for method, operation in operations.items():
                    operation["security"] = (
                        [{"HostBootstrap": []}]
                        if path == "/api/v1/session"
                        else [{"HostSession": [], **({"CSRF": []} if method == "post" else {})}]
                    )
            app.openapi_schema = spec
        return app.openapi_schema

    app.openapi = openapi

    def response_error(code, message, status=403, retryable=False, manual=False):
        return JSONResponse(
            status_code=status,
            content=ErrorResponse(
                error={
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                    "manual_action_required": manual,
                }
            ).model_dump(mode="json"),
        )

    @app.exception_handler(AgentFailure)
    async def domain_error(request, exc):
        code = exc.error.code
        return response_error(
            code,
            "请求被拒绝或证据无法校验；请检查授权、版本与确认状态",
            409 if code in {"WEB_BUSY", "WEB_IDEMPOTENCY_CONFLICT", "SCHEMA_STALE"} else 403,
            manual=code == "RECOVERY_UNCERTAIN",
        )

    @app.exception_handler(ParseFailure)
    async def parse_error(request, exc):
        return response_error(exc.error.code, "文件未通过有界解析或 Schema 校验", 422)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return response_error("WEB_VALIDATION", "请求格式不符合 API 契约", 422)

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return response_error("WEB_INTERNAL", "服务暂时无法处理请求；内部详情不公开", 500)

    @app.middleware("http")
    async def guard(request, call_next):
        if request.headers.get("host") != policy.api_host:
            return response_error("WEB_HOST", "Host is not authorized")
        origin = request.headers.get("origin")
        if origin and origin != policy.ui_origin:
            return response_error("WEB_ORIGIN", "Origin is not authorized")
        # Reject before multipart buffers or arbitrary request bodies are allocated.
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 11 * 1024**2:
            return response_error("WEB_BODY_LIMIT", "Request body exceeds quota", 413)
        if request.method not in {"GET", "POST"}:
            return response_error("WEB_METHOD", "Method is not supported", 405)
        if request.method == "POST" and origin != policy.ui_origin:
            return response_error("WEB_ORIGIN", "Mutations require an authorized Origin")
        try:
            if request.url.path != "/api/v1/session":
                request.state.actor_session_hash = store.authenticate(
                    request.cookies.get("datapilot_session"),
                    request.headers.get("x-csrf-token", "") if request.method == "POST" else None,
                )
            elif request.method != "POST" or not secrets.compare_digest(
                request.headers.get("x-datapilot-host-key", ""), policy.secret.get_secret_value()
            ):
                deny()
        except AgentFailure:
            return response_error("WEB_FORBIDDEN", "A current host-authorized session is required")
        result = await call_next(request)
        result.headers["Cache-Control"] = "no-store"
        result.headers["X-Content-Type-Options"] = "nosniff"
        result.headers["Referrer-Policy"] = "no-referrer"
        return result

    @app.post("/api/v1/session", response_model=SessionView)
    def session():
        token, csrf = store.session()
        response = JSONResponse(
            {
                "schema_version": "api-v1",
                "csrf_token": csrf,
                "deployment": "trusted-local-single-user",
            }
        )
        response.set_cookie(
            "datapilot_session",
            token,
            httponly=True,
            samesite="strict",
            max_age=8 * 3600,
            path="/api/v1",
        )
        return response

    @app.get("/api/v1/health", response_model=HealthView)
    def health():
        with store.transaction() as conn:
            conn.exec_driver_sql("SELECT 1 FROM execution.web_runs LIMIT 0")
        return {
            "status": "ready",
            "mode": settings.llm_mode,
            "durable": True,
            "telemetry": policy.telemetry,
            "production_multi_tenant": False,
        }

    @app.post("/api/v1/uploads", response_model=UploadView)
    async def upload(file: Annotated[UploadFile, File()], options: str = Form("{}")):
        data = await file.read(10 * 1024**2 + 1)
        try:
            opts = ParseOptions.model_validate_json(options)
        except ValueError:
            deny("WEB_VALIDATION", "Invalid parser options")
        return await asyncio.to_thread(service.upload, data, file.filename or "", opts)

    @app.post("/api/v1/samples", response_model=UploadView)
    def sample():
        path = ROOT / "tests/fixtures/semantics/saas_metrics.xlsx"
        return service.upload(path.read_bytes(), path.name)

    @app.get("/api/v1/uploads/{id_}", response_model=UploadView)
    def get_upload(id_: str):
        return preview(store.upload(id_))

    @app.post("/api/v1/uploads/{id_}/confirm", response_model=UploadView)
    def confirm(id_: str, request: SchemaReview):
        return service.confirm(id_, request)

    @app.post(
        "/api/v1/uploads/{id_}/import",
        response_model=ImportResult,
    )
    def import_upload(id_: str, request: ImportUpload):
        return run_async(service.import_upload(id_, request))

    @app.get("/api/v1/datasets", response_model=DatasetViews)
    def datasets(offset: int = Query(0, ge=0, le=1_000_000), limit: int = Query(100, ge=1, le=100)):
        rows = store.datasets(offset=offset, limit=limit)
        return {
            "datasets": [public_schema(p) for p in rows[:limit]],
            "offset": offset,
            "limit": limit,
            "next_offset": offset + limit if len(rows) > limit else None,
        }

    @app.get("/api/v1/datasets/{id_}/versions/{version}", response_model=DatasetView)
    def dataset(id_: str, version: int):
        return public_schema(run_async(service.dataset(id_, version)))

    @app.get(
        "/api/v1/datasets/{id_}/versions/{version}/sample-mapping",
        response_model=SemanticDraft,
    )
    def sample_mapping(id_: str, version: int):
        p = run_async(service.dataset(id_, version))
        # An explicit template ONLY for the committed synthetic fixture, never guessed.
        import hashlib

        from datapilot.data.semantic_demo import mapping_draft

        sample = ROOT / "tests/fixtures/semantics/saas_metrics.xlsx"
        if p["schema"]["source_sha256"] != hashlib.sha256(sample.read_bytes()).hexdigest():
            deny("MANUAL_MAPPING_REQUIRED", "Provide a reviewed semantic mapping for your data")
        from datapilot.datasets.contracts import DatasetSchema

        return mapping_draft(DatasetSchema.model_validate(p["schema"]))

    @app.post(
        "/api/v1/semantics/confirm",
        response_model=SemanticVersion,
    )
    def semantics(request: SemanticReview):
        return run_async(service.confirm_definition(request, "semantics"))

    @app.post(
        "/api/v1/metrics/confirm",
        response_model=MetricVersion,
    )
    def metric(request: MetricReview):
        return run_async(service.confirm_definition(request, "metrics"))

    @app.post(
        "/api/v1/datasets/{id_}/versions/{version}/documents", response_model=DocumentIngested
    )
    async def documents(
        id_: str, version: int, file: Annotated[UploadFile, File()], reviewed: bool = Form(False)
    ):
        data = await file.read(256 * 1024 + 1)
        return await asyncio.to_thread(
            run_async, service.documents(id_, version, data, file.filename or "", reviewed)
        )

    @app.get("/api/v1/corpora", response_model=CorporaView)
    def corpora():
        return {
            "corpora": [
                {k: row[k] for k in ("corpus_id", "index_version", "dataset_id", "dataset_version")}
                for row in store.corpora()
            ]
        }

    @app.post("/api/v1/tasks", response_model=Acknowledgement)
    def create(request: CreateTask, idempotency_key: str = Header(...)):
        if request.documents:
            deny("GOAL_CONFIRMATION_REQUIRED", "文档任务须通过对话中的完整有限合同确认")
        payload = run_async(service.task_payload(request))
        return store.command(idempotency_key, "create", payload, payload=payload)

    @app.get("/api/v1/tasks", response_model=TaskIDs)
    def tasks():
        with store.transaction() as conn:
            from datapilot.persistence.backend import execute

            ids = (
                execute(
                    conn,
                    "SELECT run_id FROM execution.web_runs WHERE owner=:o "
                    "AND expires_at>now() ORDER BY created_at DESC LIMIT 30",
                    o=policy.owner,
                )
                .scalars()
                .all()
            )
        return {"run_ids": ids}

    @app.get("/api/v1/tasks/{id_}", response_model=TaskView)
    def task(id_: UUID):
        return run_async(service.inspect(str(id_)))[0]

    @app.post("/api/v1/tasks/{id_}/{action}", response_model=Acknowledgement)
    def action(id_: UUID, action: str, request: TaskAction, idempotency_key: str = Header(...)):
        if action not in {"approve", "resume", "cancel"}:
            deny("WEB_ACTION", "Unsupported task action")
        row = store.run(str(id_))
        if action != "cancel":
            run_async(service.authorize_run(str(id_)))
        old = store.replay(idempotency_key, action, request.model_dump(mode="json"), str(id_))
        if old and action != "cancel":
            return old
        if action == "cancel":
            from datapilot.persistence.backend import Backend
            from datapilot.persistence.inspection import control_state

            _, terminal = run_async(
                control_state(service.settings, str(id_), policy.owner, row["payload"]["question"])
            )
            result = old or store.command(
                idempotency_key,
                action,
                request.model_dump(mode="json"),
                run_id=str(id_),
                no_op=terminal,
            )
            if not terminal:
                backend = Backend(
                    service.settings.runtime_database_url.get_secret_value(), str(id_), policy.owner
                )
                try:
                    try:
                        backend.cancel()
                    except AgentFailure as exc:
                        # Missing Runtime is legitimate only before initialization. The
                        # monotonic outbox flag then prevents starting after registration.
                        from datapilot.persistence.backend import execute

                        with backend.engine.connect() as conn:
                            exists = execute(
                                conn, "SELECT 1 FROM execution.runs WHERE run_id=:r", r=str(id_)
                            ).first()
                        if exists or exc.error.code != "RECOVERY_FORBIDDEN":
                            raise
                finally:
                    backend.close()
            return result
        view, _ = run_async(service.inspect(str(id_)))
        if action == "approve" and (view.status != "awaiting_review" or not request.confirmed):
            deny("WEB_APPROVAL", "Only a reviewed pending host approval can proceed")
        if action == "resume" and view.status not in {"paused", "failed"}:
            deny("WEB_RESUME", "Only a safely paused or retryable run may resume")
        if view.error and view.error.manual_action_required and action != "cancel":
            deny("RECOVERY_UNCERTAIN", "Manual reconciliation is required")
        result = store.command(
            idempotency_key, action, request.model_dump(mode="json"), run_id=str(id_)
        )
        return result

    @app.get("/api/v1/tasks/{id_}/report", response_model=ReportView)
    def report(id_: UUID):
        view, verified = run_async(service.inspect(str(id_)))
        if not view.report_available:
            deny("REPORT_NOT_READY", "No currently verified authorized report is available")
        return report_view(str(id_), verified)

    @app.get("/api/v1/tasks/{id_}/evidence/{evidence_id}", response_model=MetricFact)
    def evidence(id_: UUID, evidence_id: UUID):
        view = report(id_)
        matches = [f for f in view.facts if f.evidence_id == str(evidence_id)]
        if len(matches) != 1:
            deny()
        return matches[0]

    @app.get("/api/v1/tasks/{id_}/trace", response_model=TraceView)
    def trace(id_: UUID):
        view, _ = run_async(service.inspect(str(id_)))
        if view.execution_status is None:
            # A host-authorized outbox command may precede runtime registration.
            # No calls have been observed yet; do not fabricate a runtime record.
            return TraceView(
                run_id=str(id_),
                usage_source="provider" if settings.llm_mode == "live" else "mock",
                calls=[],
                routes=[],
                journal_replay_is_provider_cache=False,
                cost={"amount": None, "status": "price_and_invoice_not_available"},
                remote_telemetry=False,
                local_export_succeeded=None,
            )
        from datapilot.web.telemetry import public_trace

        return public_trace(settings, str(id_), policy)

    return app


def factory():
    return create_app(policy_file=__import__("os").environ.get("DATAPILOT_WEB_HOST_FILE"))
