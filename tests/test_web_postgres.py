"""Real PG + HTTP host + MCP. Model decisions, when used, are explicitly Fake."""

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from datapilot.persistence.session import run_async
from datapilot.web.app import create_app
from datapilot.web.config import HostPolicy
from datapilot.web.worker import execute_one

pytestmark = pytest.mark.integration
ROOT = Path(__file__).parents[1]


@pytest.fixture
def api(pg_settings, tmp_path):
    policy = HostPolicy(
        secret="local-test-host-secret",
        data_dir=tmp_path,
        api_host="testserver",
        ui_origin="http://localhost:8501",
        owner="webtest-" + uuid4().hex[:12],
    )
    app = create_app(policy=policy, settings=pg_settings, dispatch=False)
    with TestClient(app, raise_server_exceptions=True) as client:
        client.headers["Origin"] = policy.ui_origin
        r = client.post(
            "/api/v1/session", headers={"X-DataPilot-Host-Key": policy.secret.get_secret_value()}
        )
        assert r.status_code == 200, r.text
        client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        yield client, app, pg_settings


def post(client, url, body):
    r = client.post(url, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def import_sample(client):
    p = post(client, "/api/v1/samples", {})
    assert all(
        "preview_rows" not in t and all("examples" not in col for col in t["columns"])
        for t in p["tables"]
    )
    id_ = p["upload_id"]
    c = post(
        client,
        f"/api/v1/uploads/{id_}/confirm",
        {"proposal_sha256": p["proposal_sha256"], "reviewed": True},
    )
    result = post(
        client,
        f"/api/v1/uploads/{id_}/import",
        {
            "confirmation_sha256": c["confirmation"]["confirmation_sha256"],
            "name": "web-test-" + uuid4().hex[:12],
        },
    )
    id_, ver = result["dataset_id"], result["version"]
    mapping = client.get(f"/api/v1/datasets/{id_}/versions/{ver}/sample-mapping")
    assert mapping.status_code == 200, mapping.text
    semantic = post(
        client, "/api/v1/semantics/confirm", {"draft": mapping.json(), "reviewed": True}
    )
    metric = post(
        client,
        "/api/v1/metrics/confirm",
        {
            "draft": {
                "dataset_id": id_,
                "dataset_version": ver,
                "semantic_version": semantic["semantic_version"],
                "metric_id": "paid_invoice_revenue",
            },
            "reviewed": True,
        },
    )
    return {
        "question": "计算2025年10月已支付账单收入",
        "require_review": True,
        "metrics": [
            {
                "goal_id": "revenue",
                "dataset_id": id_,
                "dataset_version": ver,
                "semantic_version": semantic["semantic_version"],
                "metric_id": "paid_invoice_revenue",
                "metric_version": metric["metric_version"],
                "window": {"start": "2025-10-01", "end_exclusive": "2025-11-01"},
            }
        ],
    }


def test_api_preview_confirm_metric_durable_report(api):
    c, app, settings = api
    request = import_sample(c)
    c.headers["Idempotency-Key"] = uuid4().hex
    ack = post(c, "/api/v1/tasks", request)
    assert post(c, "/api/v1/tasks", request) == ack
    altered = {**request, "question": "另一个目标"}
    assert c.post("/api/v1/tasks", json=altered).status_code == 409
    id_ = ack["run_id"]
    assert c.get(f"/api/v1/tasks/{id_}").json()["status"] == "pending"
    pending_trace = c.get(f"/api/v1/tasks/{id_}/trace")
    assert pending_trace.status_code == 200, pending_trace.text
    assert pending_trace.json()["calls"] == []
    assert pending_trace.json()["routes"] == []
    run_async(execute_one(settings, app.state.store, id_))
    state = c.get(f"/api/v1/tasks/{id_}")
    assert state.status_code == 200, state.text
    assert state.json()["status"] == "awaiting_review", state.text
    assert (
        c.post(
            f"/api/v1/tasks/{id_}/approve",
            json={"confirmed": False},
            headers={"Idempotency-Key": uuid4().hex},
        ).status_code
        == 403
    )
    c.headers["Idempotency-Key"] = uuid4().hex
    approval = post(c, f"/api/v1/tasks/{id_}/approve", {"confirmed": True})
    assert post(c, f"/api/v1/tasks/{id_}/approve", {"confirmed": True}) == approval
    run_async(execute_one(settings, app.state.store, id_))
    state = c.get(f"/api/v1/tasks/{id_}")
    assert state.status_code == 200, state.text
    assert state.json()["status"] == "completed", state.text
    assert post(c, f"/api/v1/tasks/{id_}/approve", {"confirmed": True}) == approval
    report = c.get(f"/api/v1/tasks/{id_}/report")
    assert report.status_code == 200, report.text
    assert Decimal(report.json()["facts"][0]["value"]["value"]) == Decimal("300")
    c.headers["Idempotency-Key"] = uuid4().hex
    post(c, f"/api/v1/tasks/{id_}/cancel", {})
    assert c.get(f"/api/v1/tasks/{id_}").json()["status"] == "completed"
    assert "candidate_sql" not in report.text and "query_sql" not in report.text
    assert c.get(f"/api/v1/tasks/{uuid4()}").status_code == 403
    assert c.get(f"/api/v1/tasks/{id_}/evidence/{uuid4()}").status_code == 403


def test_status_read_during_worker_commit_does_not_compare_new_state_to_old_artifacts(
    api, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor

    from datapilot.persistence.backend import DurableArtifacts

    c, app, settings = api
    request = import_sample(c)
    c.headers["Idempotency-Key"] = uuid4().hex
    id_ = post(c, "/api/v1/tasks", request)["run_id"]
    run_async(execute_one(settings, app.state.store, id_))
    c.headers["Idempotency-Key"] = uuid4().hex
    post(c, f"/api/v1/tasks/{id_}/approve", {"confirmed": True})
    original = DurableArtifacts.export
    cut = False

    def interleaved_export(store):
        nonlocal cut
        snapshot = original(store)
        if not cut and store.backend.run_id == id_:
            cut = True
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(run_async, execute_one(settings, app.state.store, id_)).result(
                    timeout=120
                )
        return snapshot

    monkeypatch.setattr(DurableArtifacts, "export", interleaved_export)
    observed = c.get(f"/api/v1/tasks/{id_}")
    assert observed.status_code == 200, observed.text
    assert cut
    assert c.get(f"/api/v1/tasks/{id_}").json()["status"] == "completed"
    assert c.get(f"/api/v1/tasks/{id_}/report").status_code == 200


def test_session_host_origin_csrf_validation(api):
    c, _, _ = api
    assert c.get("/api/v1/health", headers={"Host": "evil.test"}).status_code == 403
    assert c.post("/api/v1/samples", headers={"Origin": "https://evil.test"}).status_code == 403
    assert c.post("/api/v1/samples", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert c.post("/api/v1/tasks", json={"owner": "other"}).status_code == 422
    assert c.post("/api/v1/uploads", files={"file": ("../x.csv", b"a\n1")}).status_code == 403


def test_csv_is_real_upload_and_requires_confirmation(api):
    c, _, _ = api
    r = c.post("/api/v1/uploads", files={"file": ("业务.csv", b"id,amount\n001,1.20\n002,2.30\n")})
    assert r.status_code == 200, r.text
    p = r.json()
    assert (
        c.post(
            f"/api/v1/uploads/{p['upload_id']}/import",
            json={"confirmation_sha256": "0" * 64, "name": "unconfirmed"},
        ).status_code
        == 403
    )
    assert p["tables"][0]["columns"][0]["suggested_type"] == "TEXT"


def test_real_document_upload_retrieval_report_and_source_ref(api):
    from test_cross_source_postgres import ReportDecisions

    c, app, settings = api
    request = import_sample(c)
    request["require_review"] = False
    metric = request["metrics"][0]
    doc = (ROOT / "tests/fixtures/reporting/billing.md").read_bytes()
    path = f"/api/v1/datasets/{metric['dataset_id']}/versions/{metric['dataset_version']}/documents"
    r = c.post(path, files={"file": ("billing.md", doc)}, data={"reviewed": "true"})
    assert r.status_code == 200, r.text
    assert r.json()["embedding_fixture"] is False
    query = "已付款账单收入和经常性订阅金额有什么区别？"
    request["documents"] = {
        "question": query,
        "metric_goals": ["revenue"],
        "corpus_ids": [r.json()["corpus_id"]],
    }
    c.headers["Idempotency-Key"] = uuid4().hex
    id_ = post(c, "/api/v1/tasks", request)["run_id"]
    run_async(execute_one(settings, app.state.store, id_, transport=ReportDecisions(query)))
    state = c.get(f"/api/v1/tasks/{id_}")
    assert state.status_code == 200, state.text
    assert state.json()["status"] == "completed", state.text
    report = c.get(f"/api/v1/tasks/{id_}/report")
    assert report.status_code == 200, report.text
    assert report.json()["citations"]
    assert "excerpt" not in report.text and "payment_status='paid'" not in report.text
    assert "body" not in report.text
    assert report.json()["citations"][0]["citation"]["source_sha256"] == r.json()["source_sha256"]
    trace = c.get(f"/api/v1/tasks/{id_}/trace")
    assert trace.status_code == 200, trace.text
    assert trace.json()["usage_source"] == "mock"
    assert trace.json()["cost"]["amount"] is None
    assert "SELECT" not in trace.text and doc.decode().strip() not in trace.text


def test_expired_upload_scope_revocation_and_request_quotas(api):
    import sqlalchemy as sa

    from datapilot.db.management import management_url

    c, app, _ = api
    p = post(c, "/api/v1/samples", {})
    owner = sa.create_engine(management_url("owner"), hide_parameters=True)
    with owner.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE execution.web_uploads SET expires_at=now()-interval '1 second' "
                "WHERE upload_id=:id"
            ),
            {"id": p["upload_id"]},
        )
    assert c.get(f"/api/v1/uploads/{p['upload_id']}").status_code == 403
    assert (
        c.post(
            "/api/v1/semantics/confirm",
            content=b"x" * (400 * 1024),
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    request = import_sample(c)
    metric = request["metrics"][0]
    with app.state.store.transaction() as conn:
        conn.execute(
            sa.text(
                "UPDATE execution.web_datasets SET enabled=false WHERE owner=:o AND dataset_id=:d"
            ),
            {"o": app.state.store.policy.owner, "d": metric["dataset_id"]},
        )
    assert (
        c.post("/api/v1/tasks", json=request, headers={"Idempotency-Key": uuid4().hex}).status_code
        == 403
    )
    owner.dispose()


def test_pending_cancel_is_idempotent_without_graph_execution(api):
    c, app, settings = api
    request = import_sample(c)
    c.headers["Idempotency-Key"] = uuid4().hex
    id_ = post(c, "/api/v1/tasks", request)["run_id"]
    row = app.state.store.run(id_)
    app.state.store.mark(
        id_,
        row["command_seq"],
        "blocked",
        {"code": "WEB_EXECUTION_ERROR", "message": "执行启动失败", "retryable": True},
    )
    failed = c.get(f"/api/v1/tasks/{id_}")
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "failed"
    assert failed.json()["error"]["code"] == "WEB_EXECUTION_ERROR"
    c.headers["Idempotency-Key"] = uuid4().hex
    ack = post(c, f"/api/v1/tasks/{id_}/cancel", {})
    assert post(c, f"/api/v1/tasks/{id_}/cancel", {}) == ack
    run_async(execute_one(settings, app.state.store, id_))
    assert c.get(f"/api/v1/tasks/{id_}").json()["status"] == "cancelled"


def test_revoked_data_scope_does_not_prevent_owner_cancellation(api):
    import sqlalchemy as sa

    from datapilot.persistence.backend import Backend

    c, app, settings = api
    request = import_sample(c)
    c.headers["Idempotency-Key"] = uuid4().hex
    id_ = post(c, "/api/v1/tasks", request)["run_id"]
    run_async(execute_one(settings, app.state.store, id_))
    with app.state.store.transaction() as conn:
        conn.execute(
            sa.text(
                "UPDATE execution.web_datasets SET enabled=false WHERE owner=:o AND dataset_id=:d"
            ),
            {"o": app.state.store.policy.owner, "d": request["metrics"][0]["dataset_id"]},
        )
    assert c.get(f"/api/v1/tasks/{id_}").status_code == 403
    c.headers["Idempotency-Key"] = uuid4().hex
    ack = post(c, f"/api/v1/tasks/{id_}/cancel", {})
    assert post(c, f"/api/v1/tasks/{id_}/cancel", {}) == ack
    run_async(execute_one(settings, app.state.store, id_))
    backend = Backend(
        settings.runtime_database_url.get_secret_value(), id_, app.state.store.policy.owner
    )
    try:
        assert backend.cancelled()
    finally:
        backend.close()


def test_concurrent_idempotency_and_owner_expiry_are_not_browser_authority(api):
    from concurrent.futures import ThreadPoolExecutor

    import sqlalchemy as sa

    from datapilot.db.management import management_url
    from datapilot.web.store import WebStore

    c, app, _ = api
    request = import_sample(c)
    body = run_async(
        app.state.service.task_payload(
            __import__(
                "datapilot.web.contracts", fromlist=["CreateTask"]
            ).CreateTask.model_validate(request)
        )
    )
    key = uuid4().hex
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: app.state.store.command(key, "create", body, payload=body), range(4))
        )
    assert len({r["run_id"] for r in results}) == 1
    other = WebStore(
        management_url("web"),
        app.state.store.policy.model_copy(update={"owner": "other-" + uuid4().hex[:8]}),
    )
    foreign = other.command(uuid4().hex, "create", body, payload=body)["run_id"]
    other.close()
    assert c.get(f"/api/v1/tasks/{foreign}").status_code == 403
    owner = sa.create_engine(management_url("owner"), hide_parameters=True)
    id_ = results[0]["run_id"]
    with owner.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE execution.web_runs SET expires_at=now()-interval '1 second' WHERE run_id=:r"
            ),
            {"r": id_},
        )
    assert c.get(f"/api/v1/tasks/{id_}").status_code == 403
    assert c.get(f"/api/v1/tasks/{id_}/evidence/{uuid4()}").status_code == 403
    owner.dispose()


def test_provider_failure_is_visible_and_unknown_budget_is_not_retried(api):
    from datapilot.contracts import AgentFailure

    class RateLimited:
        async def respond(self, *args):
            raise AgentFailure(
                "MODEL_RATE_LIMIT", "private provider error must not leak", retryable=True
            )

    c, app, settings = api
    request = import_sample(c)
    request["require_review"] = False
    c.headers["Idempotency-Key"] = uuid4().hex
    id_ = post(c, "/api/v1/tasks", request)["run_id"]
    run_async(execute_one(settings, app.state.store, id_, transport=RateLimited()))
    result = c.get(f"/api/v1/tasks/{id_}")
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "blocked", result.text
    assert result.json()["error"]["code"] == "RECOVERY_UNCERTAIN"
    assert result.json()["error"]["manual_action_required"]
    assert "private provider error" not in result.text
    assert result.json()["usage"]["total_tokens"] > 0
    assert c.get(f"/api/v1/tasks/{id_}/report").status_code == 403
