"""Real PG tests for the opt-in one-shot Web smoke admission."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from datapilot.contracts import AgentFailure
from datapilot.db.management import management_url
from datapilot.ingestion.common import digest
from datapilot.web.admission import AdmissionGate, signed_payload
from datapilot.web.app import create_app
from datapilot.web.config import HostPolicy
from datapilot.web.store import WebStore

pytestmark = pytest.mark.integration

SQL_Q = "计算 2026-09 已支付账单收入"
RAG_Q = "说明企业版退款审核时限并给出原文"
BOTH_Q = "计算 2026-09 已支付账单收入并说明企业版退款审核时限"

SQL_METRIC = {
    "dataset_id": "dataset-1",
    "dataset_version": 1,
    "semantic_version": 1,
    "metric_id": "paid_invoice_revenue",
    "metric_version": 1,
}
CORPUS = {
    "corpus_id": "corpus-1",
    "index_version": "a" * 64,
    "document_ids": ["b" * 64],
}
DOC = {
    "purpose": "facts",
    "required_facts": [{"fact_id": "fact_1", "description": "企业版退款审核时限"}],
}


def make_payload(question, kind):
    metrics = [dict(SQL_METRIC)] if kind in {"sql", "both"} else []
    document = {"question": question, **DOC} if kind in {"rag", "both"} else None
    return {
        "question": question,
        "report_scope": {"metrics": metrics, "document_goal": document},
        "rag_scope": {"corpora": [dict(CORPUS)]} if document else None,
    }


def make_case(case_id, question, kind):
    payload = make_payload(question, kind)
    report = payload["report_scope"]
    rag = payload["rag_scope"] or {}
    return {
        "case_id": case_id,
        "question_sha256": digest(question),
        "metrics": report["metrics"],
        "corpora": rag.get("corpora", []),
        "document_goal": report["document_goal"],
        "causal_requested": report.get("causal_requested", False),
        "partial_evidence_policy": report.get("partial_evidence_policy", "legacy"),
        "citation_policy": report.get("citation_policy"),
        "rag_query_policy": report.get("rag_query_policy", "legacy"),
        "rag_policy": {
            "min_score": rag.get("min_score"),
            "allow_saas": rag.get("allow_saas", False),
            "embedding_profile": rag.get("embedding_profile"),
        },
    }


def make_permit(policy, store, settings, path, *, cases=None, expires=None, owner=None):
    cases = cases or [
        make_case("case-sql", SQL_Q, "sql"),
        make_case("case-rag", RAG_Q, "rag"),
        make_case("case-both", BOTH_Q, "both"),
    ]
    now = datetime.now(UTC)
    body = {
        "schema_version": "web-smoke-admission-1",
        "kind": "datapilot-web-smoke-admission-1",
        "authorized": True,
        "approved_by_role": "project_owner",
        "source_user_authorization_ref": "test-approval-" + uuid4().hex,
        "approved_at": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (expires or now + timedelta(hours=1)).isoformat(),
        "owner": owner or policy.owner,
        "host_settings_hash": store.host_settings_hash(settings),
        "freeze_sha256": "f" * 64,
        "provider": "deepseek",
        "model": "deepseek-flash",
        "thinking": "disabled",
        "max_runs": len(cases),
        "calls_per_run": 8,
        "tokens_per_run": 18000,
        "campaign_calls": 8 * len(cases),
        "campaign_token_units": 18000 * len(cases),
        "concurrency": 1,
        "automatic_retries": 0,
        "max_output_tokens": 1200,
        "task_timeout_seconds": 180,
        "campaign_timeout_seconds": 1800,
        "cases": cases,
    }
    key = os.environ["DATAPILOT_SMOKE_ADMISSION_KEY"]
    body["signature"] = hmac.new(key.encode(), signed_payload(body), hashlib.sha256).hexdigest()
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return body


@pytest.fixture
def admission(pg_settings, tmp_path, monkeypatch):
    key = "k" * 48
    monkeypatch.setenv("DATAPILOT_SMOKE_ADMISSION_KEY", key)
    policy = HostPolicy(
        secret=key,
        data_dir=tmp_path,
        api_host="testserver",
        ui_origin="http://localhost:8501",
        owner="smoke-" + uuid4().hex[:10],
        smoke_admission_file=tmp_path / "permit.json",
    )
    settings = pg_settings.model_copy(update={"max_parallel_workers": 1})
    store = WebStore(management_url("web"), policy)
    try:
        yield policy, store, settings, tmp_path / "permit.json"
    finally:
        store.close()


def reserve(gate, payload, message_id):
    with gate.store.transaction() as conn:
        existing, case, _ = gate.reserve(conn, payload, message_id)
        if existing:
            return existing
        run_id = str(uuid4())
        gate.attach(conn, case["case_id"], run_id)
        return run_id


def assert_code(code, function):
    with pytest.raises(AgentFailure) as exc:
        function()
    assert exc.value.error.code == code


def test_disabled_gate_is_a_noop(admission):
    policy, store, settings, path = admission
    disabled = HostPolicy(**{**policy.model_dump(), "smoke_admission_file": None})
    gate = AdmissionGate(disabled, store, settings)
    assert not gate.enabled
    assert gate.reserve(None, make_payload(SQL_Q, "sql"), "m") == (None, None, None)


def test_unsigned_expired_wrong_owner_and_stop_are_rejected(admission, monkeypatch):
    policy, store, settings, path = admission
    gate = AdmissionGate(policy, store, settings)
    path.write_text("{}", encoding="utf-8")
    assert_code("SMOKE_ADMISSION_SIGNATURE", gate.validate)

    make_permit(policy, store, settings, path, expires=datetime.now(UTC) - timedelta(seconds=1))
    assert_code("SMOKE_ADMISSION_EXPIRED", gate.validate)

    make_permit(policy, store, settings, path, owner="someone-else")
    assert_code("SMOKE_ADMISSION_OWNER", gate.validate)

    make_permit(policy, store, settings, path)
    stop = path.parent / "STOP"
    stop.write_text("stop", encoding="utf-8")
    body = json.loads(path.read_text(encoding="utf-8"))
    body["stop_file"] = str(stop)
    body["signature"] = hmac.new(
        os.environ["DATAPILOT_SMOKE_ADMISSION_KEY"].encode(),
        signed_payload(body),
        hashlib.sha256,
    ).hexdigest()
    path.write_text(json.dumps(body), encoding="utf-8")
    assert_code("SMOKE_STOPPED", gate.validate)


def test_legal_reservation_persists_and_same_request_returns_run(admission):
    policy, store, settings, path = admission
    make_permit(policy, store, settings, path)
    gate = AdmissionGate(policy, store, settings)
    payload = make_payload(SQL_Q, "sql")
    message = str(uuid4())
    run_id = reserve(gate, payload, message)
    assert run_id
    with store.transaction() as conn:
        existing, case, _ = gate.reserve(conn, payload, message)
    assert existing == run_id and case["case_id"] == "case-sql"
    with store.transaction() as conn:
        gate.check_run(run_id)
        assert conn.execute(
            __import__("sqlalchemy").text(
                "SELECT case_id,run_id FROM execution.web_smoke_admissions WHERE owner=:o"
            ),
            {"o": policy.owner},
        ).one() == ("case-sql", run_id)


def test_second_message_or_changed_input_cannot_reuse_case(admission):
    policy, store, settings, path = admission
    make_permit(policy, store, settings, path)
    gate = AdmissionGate(policy, store, settings)
    first, second = str(uuid4()), str(uuid4())
    run_id = reserve(gate, make_payload(SQL_Q, "sql"), first)
    with store.transaction() as conn:
        assert_code(
            "SMOKE_CASE_CONSUMED",
            lambda: gate.reserve(conn, make_payload(SQL_Q, "sql"), second),
        )
        assert_code(
            "SMOKE_NOT_ADMITTED",
            lambda: gate.reserve(conn, make_payload("another question", "sql"), first),
        )
    assert run_id


def test_three_cases_are_allowed_but_a_fourth_is_not_admitted(admission):
    policy, store, settings, path = admission
    make_permit(policy, store, settings, path)
    gate = AdmissionGate(policy, store, settings)
    for i, (q, kind) in enumerate(((SQL_Q, "sql"), (RAG_Q, "rag"), (BOTH_Q, "both"))):
        assert reserve(gate, make_payload(q, kind), f"message-{uuid4()}-{i}")
    with store.transaction() as conn:
        assert_code(
            "SMOKE_NOT_ADMITTED",
            lambda: gate.reserve(conn, make_payload("fourth question", "sql"), str(uuid4())),
        )


def test_restart_keeps_admission_and_permit_change_invalidates_run(admission):
    policy, store, settings, path = admission
    make_permit(policy, store, settings, path)
    gate = AdmissionGate(policy, store, settings)
    run_id = reserve(gate, make_payload(SQL_Q, "sql"), str(uuid4()))
    store.close()
    reopened = WebStore(management_url("web"), policy)
    try:
        again = AdmissionGate(policy, reopened, settings)
        with reopened.transaction():
            again.check_run(run_id)
        make_permit(
            policy,
            reopened,
            settings,
            path,
            cases=[
                make_case("case-sql", "replacement question", "sql"),
                make_case("case-rag", RAG_Q, "rag"),
                make_case("case-both", BOTH_Q, "both"),
            ],
        )
        assert_code("SMOKE_AUTHORIZATION_CHANGED", lambda: again.check_run(run_id))
    finally:
        reopened.close()


def test_config_change_is_rejected(admission):
    policy, store, settings, path = admission
    make_permit(policy, store, settings, path)
    changed = settings.model_copy(update={"max_model_calls": 7})
    gate = AdmissionGate(policy, store, changed)
    assert_code("SMOKE_ADMISSION_CONFIG", gate.validate)


def test_wrong_case_shape_is_not_admitted(admission):
    policy, store, settings, path = admission
    make_permit(policy, store, settings, path)
    gate = AdmissionGate(policy, store, settings)
    wrong = make_payload(SQL_Q, "sql")
    wrong["report_scope"]["metrics"][0]["dataset_version"] = 2
    with store.transaction() as conn:
        assert_code(
            "SMOKE_NOT_ADMITTED",
            lambda: gate.reserve(conn, wrong, str(uuid4())),
        )


def test_http_approval_cannot_bypass_admission(pg_settings, tmp_path, monkeypatch):
    key = "k" * 48
    monkeypatch.setenv("DATAPILOT_SMOKE_ADMISSION_KEY", key)
    policy = HostPolicy(
        secret=key,
        data_dir=tmp_path,
        api_host="testserver",
        ui_origin="http://localhost:8501",
        owner="smoke-http-" + uuid4().hex[:8],
        smoke_admission_file=tmp_path / "permit.json",
    )
    settings = pg_settings.model_copy(update={"max_parallel_workers": 1})
    bootstrap_store = WebStore(management_url("web"), policy)
    try:
        make_permit(policy, bootstrap_store, settings, tmp_path / "permit.json")
    finally:
        bootstrap_store.close()
    app = create_app(policy=policy, settings=settings, dispatch=False)
    with TestClient(app, raise_server_exceptions=True) as client:
        client.headers["Origin"] = policy.ui_origin
        session = client.post(
            "/api/v1/session",
            headers={"X-DataPilot-Host-Key": policy.secret.get_secret_value()},
        )
        assert session.status_code == 200, session.text
        client.headers["X-CSRF-Token"] = session.json()["csrf_token"]
        payload = make_payload(SQL_Q, "sql")
        run_id = app.state.store.command("direct-test", "create", payload, payload=payload)[
            "run_id"
        ]
        response = client.post(
            f"/api/v1/tasks/{run_id}/approve",
            json={"confirmed": True},
            headers={"Idempotency-Key": uuid4().hex},
        )
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "SMOKE_NOT_ADMITTED"
    app.state.store.close()


def test_single_case_permit_admits_only_that_case(admission):
    policy, store, settings, path = admission
    make_permit(
        policy,
        store,
        settings,
        path,
        cases=[make_case("case-both", BOTH_Q, "both")],
    )
    gate = AdmissionGate(policy, store, settings)
    gate.validate()
    assert reserve(gate, make_payload(BOTH_Q, "both"), str(uuid4()))
    assert_code(
        "SMOKE_NOT_ADMITTED",
        lambda: reserve(gate, make_payload(SQL_Q, "sql"), str(uuid4())),
    )


def test_permit_supports_one_to_three_cases_and_rejects_four(admission):
    policy, store, settings, path = admission
    four = [make_case(f"case-{i}", f"question {i}", "sql") for i in range(4)]
    make_permit(policy, store, settings, path, cases=four)
    gate = AdmissionGate(policy, store, settings)
    assert_code("SMOKE_ADMISSION_CASES", gate.validate)


def test_concurrent_case_reservation_returns_one_run(admission):
    policy, store, settings, path = admission
    make_permit(policy, store, settings, path)
    payload = make_payload(SQL_Q, "sql")
    message = str(uuid4())
    barrier = threading.Barrier(2)

    def attempt():
        local = WebStore(management_url("web"), policy)
        try:
            gate = AdmissionGate(policy, local, settings)
            barrier.wait()
            with local.transaction() as conn:
                existing, case, _ = gate.reserve(conn, payload, message)
                if existing:
                    return existing
                run_id = str(uuid4())
                gate.attach(conn, case["case_id"], run_id)
                return run_id
        finally:
            local.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = [future.result() for future in (pool.submit(attempt), pool.submit(attempt))]
    assert first == second
    with store.transaction() as conn:
        rows = conn.execute(
            __import__("sqlalchemy").text(
                "SELECT count(*) FROM execution.web_smoke_admissions WHERE owner=:o"
            ),
            {"o": policy.owner},
        ).scalar_one()
    assert rows == 1


def test_campaign_time_bound_blocks_late_execution(admission):
    policy, store, settings, path = admission
    make_permit(policy, store, settings, path)
    gate = AdmissionGate(policy, store, settings)
    run_id = reserve(gate, make_payload(SQL_Q, "sql"), str(uuid4()))
    with store.transaction() as conn:
        conn.execute(
            __import__("sqlalchemy").text(
                "UPDATE execution.web_smoke_admissions "
                "SET admitted_at=now()-interval '2 hours' WHERE owner=:o AND run_id=:r"
            ),
            {"o": policy.owner, "r": run_id},
        )
    assert_code("SMOKE_CAMPAIGN_TIMEOUT", lambda: gate.check_run(run_id))


def test_same_question_with_changed_window_is_not_admitted(admission):
    policy, store, settings, path = admission
    make_permit(policy, store, settings, path)
    gate = AdmissionGate(policy, store, settings)
    wrong = make_payload(SQL_Q, "sql")
    wrong["report_scope"]["metrics"][0]["window"] = {
        "start": "2026-10-01",
        "end_exclusive": "2026-11-01",
    }
    with store.transaction() as conn:
        assert_code(
            "SMOKE_NOT_ADMITTED",
            lambda: gate.reserve(conn, wrong, str(uuid4())),
        )


def test_campaign_deadline_is_shared_across_cases(admission):
    policy, store, settings, path = admission
    make_permit(policy, store, settings, path)
    gate = AdmissionGate(policy, store, settings)
    first = reserve(gate, make_payload(SQL_Q, "sql"), str(uuid4()))
    second = reserve(gate, make_payload(RAG_Q, "rag"), str(uuid4()))
    with store.transaction() as conn:
        conn.execute(
            __import__("sqlalchemy").text(
                "UPDATE execution.web_smoke_admissions "
                "SET admitted_at=now()-interval '2 hours' WHERE owner=:o AND run_id=:r"
            ),
            {"o": policy.owner, "r": first},
        )
    assert_code("SMOKE_CAMPAIGN_TIMEOUT", lambda: gate.check_run(second))
