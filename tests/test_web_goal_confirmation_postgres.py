"""Real isolated HTTP/PG/MCP/BGE; explicit synthetic decisions, never paid LLM."""

import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_chat_postgres import conversation, message, request
from test_cross_source_postgres import ReportDecisions
from test_rag_only_postgres import approve_and_run
from test_web_postgres import import_sample

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.persistence.backend import Backend, execute
from datapilot.persistence.session import run_async
from datapilot.web.app import create_app
from datapilot.web.config import HostPolicy
from datapilot.web.worker import execute_one

pytestmark = pytest.mark.integration
QUESTION = "根据指定的 billing.md，总结已支付账单收入规则并给出文档引用。"
TEXT = (
    "公开合成账单规则：已支付账单收入仅计入状态为paid的账单，以CNY整数分存储；"
    "按账单日期筛选时间右开区间。这些规则不证明客户行为的因果。"
)


def session(c, policy):
    c.headers["Origin"] = policy.ui_origin
    response = c.post(
        "/api/v1/session", headers={"X-DataPilot-Host-Key": policy.secret.get_secret_value()}
    )
    assert response.status_code == 200, response.text
    c.headers["X-CSRF-Token"] = response.json()["csrf_token"]


@pytest.fixture(scope="module")
def host(portable_pg, tmp_path_factory):
    folder = tmp_path_factory.mktemp("web-goal-host")
    policy = HostPolicy(
        secret="public-local-test-secret",
        owner="goal-web-" + uuid4().hex[:12],
        data_dir=folder,
        api_host="testserver",
        ui_origin="http://localhost:8519",
    )
    app = create_app(policy=policy, settings=portable_pg, dispatch=False)
    with TestClient(app) as c:
        session(c, policy)
        metric = import_sample(c)
        m = metric["metrics"][0]
        response = c.post(
            f"/api/v1/datasets/{m['dataset_id']}/versions/{m['dataset_version']}/documents",
            files={"file": ("billing.md", TEXT.encode())},
            data={"reviewed": "true"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["embedding_fixture"] is False
        yield c, app, portable_pg, metric, response.json()


def candidate(host, *, text=QUESTION, purpose="summary", facts=None, cid=None, supersedes=None):
    c, _, _, _, corpus = host
    cid = cid or conversation(c)
    body = {
        "text": text,
        "selection": {"corpus_ids": [corpus["corpus_id"]], "document_purpose": purpose},
    }
    if facts:
        body["selection"]["required_facts"] = facts
    if supersedes:
        body["supersedes"] = supersedes
    m = request(c, f"/conversations/{cid}/messages", body)
    assert m["goal_contract"], m
    return cid, m


def decision(m):
    g = m["goal_contract"]
    return {
        "confirmed": True,
        "expected_version": g["version"],
        "expected_contract_sha256": g["contract_sha256"],
        "reviewed_contract": True,
        "covers_original_goal": True,
        "prerequisites_resolved": True,
    }


def launch_path(cid, m):
    return f"/api/v1/conversations/{cid}/messages/{m['message_id']}/launch"


def confirm(host, cid, m):
    r = host[0].post(launch_path(cid, m), json=decision(m))
    assert r.status_code == 200, r.text
    return r.json()["run_id"]


def reject(host, cid, m):
    d = decision(m)
    return host[0].post(
        launch_path(cid, m).removesuffix("launch") + "goal/reject",
        json={
            "expected_version": d["expected_version"],
            "expected_contract_sha256": d["expected_contract_sha256"],
        },
    )


def test_contract_is_pending_no_attestation_no_runtime_until_real_confirmation(host):
    c, app, _, _, _ = host
    cid, m = candidate(host)
    g = m["goal_contract"]
    assert g["status"] == "pending_confirmation" and not m["run_id"]
    assert g["original_question"] == QUESTION and g["sources"][0]["required"]
    assert g["datasets"] and g["sources"][0]["source_sha256"]
    with app.state.store.transaction() as conn:
        row = app.state.chat._message(conn, cid, m["message_id"])
    assert (
        "goal_scope_attestation" not in row["payload"]["goal_contract"]["payload"]["report_scope"]
    )
    assert c.post(launch_path(cid, m), json={"confirmed": True}).status_code == 403
    for key in (
        "confirmation_ref",
        "goal_scope_attestation",
        "completion_eligible",
        "policy_version",
    ):
        assert c.post(launch_path(cid, m), json=decision(m) | {key: True}).status_code == 422
    assert (
        c.post(
            launch_path(cid, m), json=decision(m) | {"expected_contract_sha256": "0" * 64}
        ).status_code
        == 403
    )
    assert (
        c.post(
            launch_path(cid, m), json=decision(m) | {"prerequisites_resolved": False}
        ).status_code
        == 403
    )
    assert (
        c.post(launch_path(cid, m), json=decision(m), headers={"X-CSRF-Token": "wrong"}).status_code
        == 403
    )
    assert reject(host, cid, m).status_code == 200


def test_confirmation_ack_loss_concurrent_repeat_uses_one_run_and_one_event(host):
    c, app, settings, _, _ = host
    cid, m = candidate(host)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: confirm(host, cid, m), range(2)))
    assert ids[0] == ids[1] == confirm(host, cid, m)
    id_ = ids[0]
    payload = app.state.store.run(id_)["payload"]
    e = payload["goal_confirmation"]
    assert (
        payload["report_scope"]["goal_scope_attestation"]["confirmation_ref"]
        == "web-goal:" + e["event_id"]
    )
    assert e["actor_session_hash"] and e["message_id"] == m["message_id"]
    with app.state.store.transaction() as conn:
        rows = execute(
            conn,
            "SELECT payload FROM execution.web_messages "
            "WHERE conversation_id=:c AND payload ? 'goal_event'",
            c=cid,
        ).all()
        assert len(rows) == 1 and rows[0][0]["goal_event"]["covers_original_goal"] is True
    # Scope confirmation is not execution approval; no model calls before Journal approval.
    run_async(execute_one(settings, app.state.store, id_))
    assert c.get(f"/api/v1/tasks/{id_}").json()["status"] == "awaiting_review"
    assert c.get(f"/api/v1/tasks/{id_}/trace").json()["calls"] == []
    assert reject(host, cid, m).status_code == 200
    run_async(execute_one(settings, app.state.store, id_))
    assert app.state.store.run(id_)["cancel_requested"]
    assert c.post(launch_path(cid, m), json=decision(m)).status_code == 403


def test_real_rag_completed_restart_and_confirmation_withdrawal(host):
    c, app, settings, _, _ = host
    cid, m = candidate(host)
    id_ = confirm(host, cid, m)
    approve_and_run(c, app, settings, id_, transport=ReportDecisions(QUESTION))
    r = c.get(f"/api/v1/tasks/{id_}/report")
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["business_completion"]["status"] == "completed", report
    assert report["citations"] and not report["facts"]
    citation = report["citations"][0]
    assert (
        citation["quotation"] == TEXT[citation["citation"]["start"] : citation["citation"]["end"]]
    )
    restarted = create_app(policy=app.state.store.policy, settings=settings, dispatch=False)
    with TestClient(restarted) as other:
        session(other, app.state.store.policy)
        assert digest(other.get(f"/api/v1/tasks/{id_}/report").json()) == digest(report)
        history = other.get(f"/api/v1/conversations/{cid}/messages").json()["messages"]
        assert history[0]["goal_contract"]["status"] == "confirmed"
        assert confirm((other, *host[1:]), cid, m) == id_
    assert reject(host, cid, m).status_code == 200
    assert c.get(f"/api/v1/tasks/{id_}/report").status_code == 403
    assert (
        c.post(
            f"/api/v1/tasks/{id_}/resume", json={}, headers={"Idempotency-Key": uuid4().hex}
        ).status_code
        == 403
    )


def test_quoted_fact_is_host_pinned_and_report_completes(host):
    c, app, settings, _, _ = host
    quote = "已支付账单收入仅计入状态为paid的账单，以CNY整数分存储；"
    cid, m = candidate(
        host,
        purpose="facts",
        facts=[
            {
                "fact_id": "paid_rule",
                "description": "已支付账单收入的计入规则",
                "quotation": quote,
            }
        ],
    )
    assert m["goal_contract"]["can_confirm"] is True, m["goal_contract"]["unresolved"]
    assert (
        m["goal_contract"]["review"]["request"]["documents"]["required_facts"][0]["quotation"]
        == quote
    )
    id_ = confirm(host, cid, m)
    approve_and_run(c, app, settings, id_, transport=ReportDecisions(QUESTION))
    report = c.get(f"/api/v1/tasks/{id_}/report")
    assert report.status_code == 200, report.text
    assert report.json()["business_completion"]["status"] == "completed"
    assert any(item["quotation"] == quote for item in report.json()["citations"])


def test_missing_quoted_fact_stays_unconfirmable(host):
    c, _, _, _, _ = host
    cid, m = candidate(
        host,
        purpose="facts",
        facts=[
            {
                "fact_id": "paid_rule",
                "description": "已支付账单收入的计入规则",
                "quotation": "这段原文不在授权文档中",
            }
        ],
    )
    assert m["goal_contract"]["can_confirm"] is False
    assert any("fact_proof_missing" in item for item in m["goal_contract"]["unresolved"])


def test_fact_requirements_are_not_proofs_even_after_confirmation(host):
    c, app, settings, _, _ = host
    cid, m = candidate(
        host,
        purpose="facts",
        facts=[{"fact_id": "unpublished", "description": "下一年度的退款比例"}],
    )
    id_ = confirm(host, cid, m)
    approve_and_run(c, app, settings, id_, transport=ReportDecisions(QUESTION))
    report = c.get(f"/api/v1/tasks/{id_}/report")
    assert report.status_code == 200, report.text
    assert report.json()["business_completion"]["status"] in {"partial", "unavailable"}
    assert not report.json()["facts"]
    assert reject(host, cid, m).status_code == 200


def test_edit_supersedes_and_retry_cannot_reuse_old_confirmation(host, monkeypatch):
    c, app, _, _, corpus = host
    cid, m = candidate(host)
    id_ = confirm(host, cid, m)
    key = uuid4().hex
    body = {
        "text": "根据指定的billing.md，总结已支付账单的日期边界规则并给出引用。",
        "selection": {"corpus_ids": [corpus["corpus_id"]], "document_purpose": "summary"},
        "supersedes": m["message_id"],
    }
    original = app.state.service.cancel_runtime

    async def lost(_):
        raise AgentFailure("WEB_TEMPORARY", "Synthetic lost cancellation acknowledgement")

    monkeypatch.setattr(app.state.service, "cancel_runtime", lost)
    failed = c.post(
        f"/api/v1/conversations/{cid}/messages", json=body, headers={"Idempotency-Key": key}
    )
    assert failed.status_code == 403
    monkeypatch.setattr(app.state.service, "cancel_runtime", original)
    new = request(c, f"/conversations/{cid}/messages", body, key)
    assert (
        new["message_id"] != m["message_id"]
        and new["goal_contract"]["status"] == "pending_confirmation"
    )
    assert new["goal_contract"]["version"] > m["goal_contract"]["version"]
    assert app.state.store.run(id_)["cancel_requested"]
    assert c.post(launch_path(cid, m), json=decision(m)).status_code == 403
    assert c.post(launch_path(cid, new), json=decision(m)).status_code == 403
    assert reject(host, cid, new).status_code == 200


def test_exhaustive_goal_cannot_be_self_approved_and_followup_has_no_inherited_proof(host):
    c, app, _, _, _ = host
    cid, m = candidate(host, text="逐篇核对所有文档证明材料齐备，不能遗漏任何来源。")
    assert m["goal_contract"]["can_confirm"] is False and m["goal_contract"]["unresolved"]
    assert c.post(launch_path(cid, m), json=decision(m)).status_code == 403
    follow = message(c, cid, "那请比较其他团队的全部材料")
    assert not follow["run_id"]
    with app.state.store.transaction() as conn:
        assert (
            "goal_confirmation"
            not in app.state.chat._message(conn, cid, follow["message_id"])["payload"]
        )
    assert reject(host, cid, m).status_code == 200


def test_cross_conversation_confirmation_and_client_scope_forgery_are_rejected(host):
    c, _, _, metric, corpus = host
    cid, m = candidate(host)
    other = conversation(c)
    assert c.post(launch_path(other, m), json=decision(m)).status_code == 403
    for field in ("goal_contract", "scope_attestation", "goal_confirmation", "role"):
        assert (
            c.post(
                f"/api/v1/conversations/{cid}/messages",
                json={"text": QUESTION, field: {}},
                headers={"Idempotency-Key": uuid4().hex},
            ).status_code
            == 422
        )
    forged = {
        "text": QUESTION,
        "selection": {"corpus_ids": [str(uuid4())], "document_purpose": "summary"},
    }
    assert (
        c.post(
            f"/api/v1/conversations/{cid}/messages",
            json=forged,
            headers={"Idempotency-Key": uuid4().hex},
        ).status_code
        == 403
    )
    direct = {
        "question": QUESTION,
        "metrics": [],
        "documents": {
            "question": QUESTION,
            "metric_goals": [],
            "corpus_ids": [corpus["corpus_id"]],
            "purpose": "summary",
        },
    }
    assert (
        c.post("/api/v1/tasks", json=direct, headers={"Idempotency-Key": uuid4().hex}).status_code
        == 403
    )
    assert reject(host, cid, m).status_code == 200


def test_unknown_outcome_is_not_replaced_by_new_contract_or_retried(host):
    class LostResponse:
        async def respond(self, *args):
            raise AgentFailure("MODEL_RATE_LIMIT", "Synthetic unknown outcome", retryable=True)

    c, app, settings, _, corpus = host
    cid, m = candidate(host)
    id_ = confirm(host, cid, m)
    approve_and_run(c, app, settings, id_, transport=LostResponse())
    before = c.get(f"/api/v1/tasks/{id_}").json()
    assert before["error"]["code"] == "RECOVERY_UNCERTAIN"
    assert confirm(host, cid, m) == id_
    edited = c.post(
        f"/api/v1/conversations/{cid}/messages",
        json={
            "text": QUESTION,
            "supersedes": m["message_id"],
            "selection": {"corpus_ids": [corpus["corpus_id"]], "document_purpose": "summary"},
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert edited.status_code == 403 and edited.json()["error"]["code"] == "RECOVERY_UNCERTAIN"
    assert c.get(f"/api/v1/tasks/{id_}").json()["usage"] == before["usage"]


def test_combined_sql_rag_p3_verified_and_identity_persists(host):
    c, app, settings, metric, corpus = host
    req = metric["metrics"][0]
    cid = conversation(c)
    m = message(
        c,
        cid,
        "计算2025年10月已支付账单收入，并引用规则说明："
        "已支付账单收入仅计入状态为paid的账单，以CNY整数分存储。",
        {
            "dataset_id": req["dataset_id"],
            "dataset_version": req["dataset_version"],
            "metric_id": req["metric_id"],
            "metric_version": req["metric_version"],
            "window": req["window"],
            "corpus_ids": [corpus["corpus_id"]],
            "document_purpose": "summary",
        },
    )
    assert m["goal_contract"] and m["goal_contract"]["review"]["definitions"]
    id_ = confirm(host, cid, m)
    approve_and_run(
        c,
        app,
        settings,
        id_,
        transport=ReportDecisions(m["draft"]["request"]["documents"]["question"]),
    )
    response = c.get(f"/api/v1/tasks/{id_}/report")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["business_completion"]["status"] == "completed", report
    assert (
        Decimal(report["facts"][0]["value"]["value"]) == Decimal("300")
        and report["facts"][0]["value"]["unit"] == "CNY"
    )
    backend = Backend(
        settings.runtime_database_url.get_secret_value(), id_, app.state.store.policy.owner
    )
    try:
        with backend.engine.connect() as conn:
            old_calls = execute(
                conn, "SELECT count(*) FROM execution.calls WHERE run_id=:r", r=id_
            ).scalar_one()
        restarted = create_app(policy=app.state.store.policy, settings=settings, dispatch=False)
        with TestClient(restarted) as other:
            session(other, app.state.store.policy)
            assert other.get(f"/api/v1/tasks/{id_}/report").json() == report
        with backend.engine.connect() as conn:
            assert (
                execute(
                    conn, "SELECT count(*) FROM execution.calls WHERE run_id=:r", r=id_
                ).scalar_one()
                == old_calls
            )
    finally:
        backend.close()


def test_expiry_and_changed_scope_fail_closed_before_confirmation(host, monkeypatch):
    from datetime import datetime, timedelta

    import datapilot.web.chat as chat_module

    c, app, _, _, _ = host
    cid, m = candidate(host)
    real = chat_module.datetime

    class Future(datetime):
        @classmethod
        def now(cls, tz=None):
            return real.now(tz) + timedelta(days=8)

    with monkeypatch.context() as patch:
        patch.setattr(chat_module, "datetime", Future)
        response = c.post(launch_path(cid, m), json=decision(m))
        assert response.status_code == 403 and response.json()["error"]["code"] == "GOAL_STALE"
    assert reject(host, cid, m).status_code == 200


def test_original_web_outbox_resumes_new_goal_across_processes(host, tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    c, app, settings, _, _ = host
    cid, m = candidate(host)
    id_ = confirm(host, cid, m)
    policy = app.state.store.policy.model_dump(mode="json")
    policy["secret"] = app.state.store.policy.secret.get_secret_value()
    path = tmp_path / "host.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(
        json.dumps(
            settings.model_dump(
                mode="json",
                exclude={
                    "api_key",
                    "llm_mode",
                    "reader_database_url",
                    "upload_reader_database_url",
                    "runtime_database_url",
                    "rag_reader_database_url",
                },
            )
        ),
        encoding="utf-8",
    )

    def worker(label, *extra):
        result = subprocess.run(
            [
                sys.executable,
                "tests/web_goal_recovery_probe.py",
                str(path),
                id_,
                "--settings",
                str(settings_path),
                *extra,
            ],
            cwd=Path(__file__).parents[1],
            env={**os.environ, "PYTHONUTF8": "1"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
        (tmp_path / (label + ".log")).write_text(result.stdout + result.stderr, encoding="utf-8")
        assert result.returncode == 0, result.stderr[-600:]

    worker("register")
    assert c.get(f"/api/v1/tasks/{id_}").json()["status"] == "awaiting_review"
    request(c, f"/tasks/{id_}/approve", {"confirmed": True})
    worker("pause", "--pause-after", "worker")
    assert c.get(f"/api/v1/tasks/{id_}").json()["status"] == "paused"
    request(c, f"/tasks/{id_}/resume", {})
    worker("resume")
    response = c.get(f"/api/v1/tasks/{id_}/report")
    assert response.status_code == 200, response.text
    assert response.json()["business_completion"]["status"] == "completed"


def test_required_source_candidates_and_full_query_limit_cannot_shrink_goal(host):
    c, _, _, metric, corpus = host
    cid = conversation(c)
    selection = {
        "corpus_ids": [corpus["corpus_id"]],
        "document_purpose": "summary",
        "required_source_ids": ["0" * 64],
    }
    response = c.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"text": QUESTION, "selection": selection},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "WEB_SCOPE"
    req = metric["metrics"][0]
    selection = {
        "dataset_id": req["dataset_id"],
        "dataset_version": req["dataset_version"],
        "metric_id": req["metric_id"],
        "metric_version": req["metric_version"],
        "window": req["window"],
        "corpus_ids": [corpus["corpus_id"]],
        "document_purpose": "summary",
    }
    response = c.post(
        f"/api/v1/conversations/{cid}/messages",
        json={
            "text": "计算2025年10月已支付账单收入并引用文档规则。" + "说明" * 260,
            "selection": selection,
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "GOAL_INPUT_LIMIT"


def test_document_request_missing_corpus_requires_clarification_but_sql_still_completes(host):
    c, app, settings, metric, _ = host
    question = "计算2025年10月已支付账单收入并引用文档说明规则。"
    response = c.post(
        "/api/v1/tasks",
        json={**metric, "question": question},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert (
        response.status_code == 403
        and response.json()["error"]["code"] == "DOCUMENT_SCOPE_REQUIRED"
    )
    req = metric["metrics"][0]
    cid = conversation(c)
    msg = message(
        c,
        cid,
        question,
        {
            "dataset_id": req["dataset_id"],
            "dataset_version": req["dataset_version"],
            "metric_id": req["metric_id"],
            "metric_version": req["metric_version"],
            "window": req["window"],
        },
    )
    assert msg["draft"]["request"] is None and any(
        "文档" in item for item in msg["draft"]["missing"]
    )
    assert c.post(launch_path(cid, msg), json={"confirmed": True}).status_code == 403
    ack = request(c, "/tasks", metric)
    approve_and_run(c, app, settings, ack["run_id"])
    result = c.get("/api/v1/tasks/" + ack["run_id"] + "/report")
    assert result.status_code == 200, result.text
    assert result.json()["business_completion"]["status"] == "completed"
    assert Decimal(result.json()["facts"][0]["value"]["value"]) == Decimal("300")


def test_revoked_dataset_does_not_publish_saved_contract_or_report(host):
    import sqlalchemy as sa

    from datapilot.db.management import management_url

    c, app, _, metric, _ = host
    cid, m = candidate(host)
    # Exercise the existing grant API; this test is deliberately last for the shared snapshot.
    owner = sa.create_engine(management_url("owner"), hide_parameters=True)
    try:
        with owner.begin() as conn:
            conn.execute(
                sa.text("UPDATE execution.web_datasets SET enabled=false WHERE owner=:o"),
                {"o": app.state.store.policy.owner},
            )
    finally:
        owner.dispose()
    response = c.get(launch_path(cid, m).removesuffix("launch") + "goal")
    assert response.status_code == 403
    history = c.get(f"/api/v1/conversations/{cid}/messages").json()["messages"]
    assert history[0]["unavailable"] and history[0]["goal_contract"] is None
    assert c.post(launch_path(cid, m), json=decision(m)).status_code == 403
    assert reject(host, cid, m).status_code == 200
