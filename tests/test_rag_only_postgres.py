"""Real PG17/pgvector/MCP/CPU embeddings + scripted/Fake decisions; no paid API."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_chat_postgres import conversation, launch, message, request
from test_cross_source_postgres import ReportDecisions
from test_web_postgres import api as api

from datapilot.db.management import management_url
from datapilot.ingestion.common import digest
from datapilot.persistence.backend import Backend, execute
from datapilot.persistence.session import run_async
from datapilot.web.app import create_app
from datapilot.web.worker import execute_one

pytestmark = pytest.mark.integration
ROOT = Path(__file__).parents[1]
QUESTION = "根据已授权的 billing.md，说明文档明确记载的已支付账单收入规则，并给出对应引用。"


@pytest.fixture
def document(api):
    c, _, _ = api
    upload = request(c, "/samples", {})
    reviewed = request(
        c,
        f"/uploads/{upload['upload_id']}/confirm",
        {"proposal_sha256": upload["proposal_sha256"], "reviewed": True},
    )
    ds = request(
        c,
        f"/uploads/{upload['upload_id']}/import",
        {
            "confirmation_sha256": reviewed["confirmation"]["confirmation_sha256"],
            "name": "rag-only-test-" + uuid4().hex[:12],
        },
    )
    raw = (ROOT / "tests/fixtures/reporting/billing.md").read_bytes()
    response = c.post(
        f"/api/v1/datasets/{ds['dataset_id']}/versions/{ds['version']}/documents",
        files={"file": ("billing.md", raw)},
        data={"reviewed": "true"},
    )
    assert response.status_code == 200, response.text
    corpus = response.json()
    assert corpus["embedding_fixture"] is False
    return ds, corpus, raw


def candidate(c, corpus, text=QUESTION):
    cid = conversation(c)
    m = message(c, cid, text, {"corpus_ids": [corpus["corpus_id"]], "document_purpose": "summary"})
    assert m["draft"]["request"] and m["draft"]["request"]["metrics"] == []
    return cid, m


def approve_and_run(c, app, settings, id_, *, transport=None):
    run_async(execute_one(settings, app.state.store, id_))
    assert c.get(f"/api/v1/tasks/{id_}").json()["status"] == "awaiting_review"
    request(c, f"/tasks/{id_}/approve", {"confirmed": True})
    run_async(execute_one(settings, app.state.store, id_, transport=transport))


def test_document_only_approval_concurrency_real_citations_and_restart(api, document):
    c, app, settings = api
    ds, corpus, raw = document
    cid, m = candidate(c, corpus)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.map(
            lambda _: run_async(app.state.chat.launch(cid, m["message_id"], True)), range(2)
        )
    assert a == b == launch(c, cid, m["message_id"])
    id_ = a["run_id"]
    assert launch(c, cid, m["message_id"])["run_id"] == id_  # Committed ACK loss.
    p = app.state.store.run(id_)["payload"]
    assert p["report_scope"]["metrics"] == [] and p["contexts"] == []
    assert p["sources"][ds["dataset_id"]]
    assert p["rag_scope"]["corpora"][0]["index_version"] == corpus["index_version"]
    assert (
        c.post(
            f"/api/v1/tasks/{id_}/approve",
            json={"confirmed": False},
            headers={"Idempotency-Key": uuid4().hex},
        ).status_code
        == 403
    )
    approve_and_run(c, app, settings, id_, transport=ReportDecisions(QUESTION))
    state = c.get(f"/api/v1/tasks/{id_}").json()
    assert state["status"] == "completed" and state["business_completion"]["status"] == "completed"
    assert {t["worker"] for t in state["tasks"]} == {"rag", "report"}
    report = c.get(f"/api/v1/tasks/{id_}/report").json()
    assert not report["facts"] and not report["charts"]
    ref = report["citations"][0]
    assert ref["citation"]["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert ref["quotation"] == raw.decode()[ref["citation"]["start"] : ref["citation"]["end"]]
    backend = Backend(
        settings.runtime_database_url.get_secret_value(), id_, app.state.store.policy.owner
    )
    try:
        with backend.engine.connect() as conn:
            calls_before = execute(
                conn, "SELECT count(*) FROM execution.calls WHERE run_id=:r", r=id_
            ).scalar_one()
            assert (
                execute(
                    conn,
                    "SELECT count(*) FROM execution.calls WHERE run_id=:r "
                    "AND tool_name='submit_rag_result'",
                    r=id_,
                ).scalar_one()
                == 1
            )
        restarted = create_app(policy=app.state.store.policy, settings=settings, dispatch=False)
        with TestClient(restarted) as new:
            new.headers["Origin"] = restarted.state.store.policy.ui_origin
            session = new.post(
                "/api/v1/session",
                headers={
                    "X-DataPilot-Host-Key": restarted.state.store.policy.secret.get_secret_value()
                },
            ).json()
            new.headers["X-CSRF-Token"] = session["csrf_token"]
            assert (
                new.get(f"/api/v1/conversations/{cid}/messages").json()["messages"][0]["run_id"]
                == id_
            )
            assert digest(new.get(f"/api/v1/tasks/{id_}/report").json()) == digest(report)
        with backend.engine.connect() as conn:
            assert (
                execute(
                    conn, "SELECT count(*) FROM execution.calls WHERE run_id=:r", r=id_
                ).scalar_one()
                == calls_before
            )
    finally:
        backend.close()
    # A document-only previous Run cannot be indexed as a previous metric.
    follow = message(c, cid, "那继续查询上个月收入")
    assert follow["draft"]["request"] is None and follow["draft"]["missing"]


@pytest.mark.parametrize(
    "question",
    [
        "根据文档说明至少两份文档明确记载的账单收入规则，并引用。",
        "根据 missing.md 文档说明已付款账单收入规则，并引用。",
    ],
)
def test_insufficient_retrieval_never_becomes_document_answer_completed(api, document, question):
    c, app, settings = api
    _, corpus, _ = document
    cid, m = candidate(c, corpus, question)
    id_ = launch(c, cid, m["message_id"])["run_id"]
    # RAG can complete semantic retrieval; Report independently enforces the source name.
    approve_and_run(
        c,
        app,
        settings,
        id_,
        transport=ReportDecisions("账单收入规则") if "missing.md" in question else None,
    )
    state = c.get(f"/api/v1/tasks/{id_}").json()
    assert state["business_completion"]["status"] == "unavailable"
    report = c.get(f"/api/v1/tasks/{id_}/report").json()
    assert report["business_completion"]["missing_evidence"] and not report["citations"]
    assert not report["facts"] and not report["charts"]


@pytest.mark.parametrize("revoke", ["dataset", "corpus"])
def test_document_scope_revocation_blocks_execution_and_recovery(api, document, revoke):
    c, app, settings = api
    ds, corpus, _ = document
    cid, m = candidate(c, corpus)
    id_ = launch(c, cid, m["message_id"])["run_id"]
    run_async(execute_one(settings, app.state.store, id_))
    owner = sa.create_engine(management_url("owner"), hide_parameters=True)
    try:
        with owner.begin() as conn:
            statement = (
                "UPDATE execution.web_datasets SET enabled=false WHERE owner=:o"
                if revoke == "dataset"
                else "UPDATE execution.web_corpora SET owner=:revoked WHERE owner=:o"
            )
            conn.execute(
                sa.text(statement),
                {"o": app.state.store.policy.owner, "revoked": "revoked-" + uuid4().hex[:12]},
            )
        for action in ["approve", "resume"]:
            assert (
                c.post(
                    f"/api/v1/tasks/{id_}/{action}",
                    json={"confirmed": True},
                    headers={"Idempotency-Key": uuid4().hex},
                ).status_code
                == 403
            )
        run_async(execute_one(settings, app.state.store, id_))
        backend = Backend(
            settings.runtime_database_url.get_secret_value(), id_, app.state.store.policy.owner
        )
        try:
            with backend.engine.connect() as conn:
                assert (
                    execute(
                        conn, "SELECT count(*) FROM execution.calls WHERE run_id=:r", r=id_
                    ).scalar_one()
                    == 0
                )
        finally:
            backend.close()
    finally:
        owner.dispose()


def test_unknown_or_wrong_corpus_version_and_empty_task_are_refused(api, document):
    c, app, _ = api
    _, corpus, _ = document
    assert (
        c.post(
            "/api/v1/tasks",
            json={"question": QUESTION, "metrics": []},
            headers={"Idempotency-Key": uuid4().hex},
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/v1/tasks",
            json={
                "question": QUESTION,
                "metrics": [],
                "documents": {
                    "question": QUESTION,
                    "metric_goals": [],
                    "corpus_ids": [str(uuid4())],
                },
            },
            headers={"Idempotency-Key": uuid4().hex},
        ).status_code
        == 403
    )
    cid, m = candidate(c, corpus)
    owner = sa.create_engine(management_url("owner"), hide_parameters=True)
    try:
        with owner.begin() as conn:
            conn.execute(
                sa.text("UPDATE execution.web_corpora SET index_version=:v WHERE owner=:o"),
                {"v": "f" * 64, "o": app.state.store.policy.owner},
            )
        assert (
            c.post(
                f"/api/v1/conversations/{cid}/messages/{m['message_id']}/launch",
                json={"confirmed": True},
            ).status_code
            == 403
        )
    finally:
        owner.dispose()
