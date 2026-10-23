"""P6C.1 review counterexamples; Mock UI, real scoped PG/MCP, no paid API."""

import json
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from streamlit.testing.v1 import AppTest
from test_chat_contracts import catalog
from test_web_postgres import api as api
from test_web_postgres import import_sample

from datapilot.contracts import AgentFailure
from datapilot.persistence.backend import execute
from datapilot.persistence.session import run_async
from datapilot.rag.contracts import CorpusPin, Target
from datapilot.web.chat_contracts import ChatSelection
from datapilot.web.client import APIClient, ClientError
from datapilot.web.contracts import CreateTask
from datapilot.web.intent import resolve


@pytest.mark.parametrize(
    "question",
    [
        "对比2025-09和2025-10的收入",
        "对比上个月和本月收入",
        "对比2025年9月和十月的收入",
    ],
)
def test_multi_window_question_is_not_silently_reduced(question):
    result = resolve(question, ChatSelection(), catalog(), today=date(2026, 10, 23))
    assert result.request is None or len(result.request.metrics) == 2, result.model_dump(
        mode="json"
    )


def test_definitively_rejected_message_allows_corrected_input(monkeypatch):
    cid = str(uuid4())

    def get(_, path):
        if path == "/health":
            return {"mode": "fake"}
        if path == "/conversations":
            return {"conversations": []}
        if path.startswith("/datasets?"):
            return {"datasets": [], "next_offset": None}
        if path == "/tasks":
            return {"run_ids": []}
        if "/messages?" in path:
            return {"messages": [], "next_before": None}
        raise AssertionError(path)

    def post(_, path, body=None, **kw):
        if path == "/conversations":
            return {"conversation_id": cid}
        assert len(body["text"]) > 2000
        raise ClientError({"code": "WEB_VALIDATION", "message": "request rejected before commit"})

    monkeypatch.setattr(APIClient, "__init__", lambda self: None)
    monkeypatch.setattr(APIClient, "get", get)
    monkeypatch.setattr(APIClient, "post", post)
    ui = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "src/datapilot/web/ui.py"))
    ui.run(timeout=20)
    ui.chat_input[0].set_value("x" * 2001).run(timeout=20)
    ui.run(timeout=20)
    assert not ui.exception
    assert not ui.chat_input[0].disabled, "Known 422 rejection leaves permanent pending intent"


@pytest.mark.parametrize(
    "question",
    [
        "2025-10 monthly recurring revenue",
        "2025年10月未支付账单收入",
    ],
)
def test_explicit_incompatible_metric_is_not_replaced_by_paid_revenue(question):
    datasets = catalog()
    for selection in (
        ChatSelection(),
        ChatSelection(
            dataset_id=datasets[0]["schema"]["dataset_id"],
            dataset_version=1,
            metric_id="paid_invoice_revenue",
            metric_version=3,
        ),
    ):
        result = resolve(question, selection, datasets, today=date(2026, 10, 23))
        assert result.request is None and result.missing, result.model_dump(mode="json")


@pytest.mark.integration
def test_legacy_task_rejects_non_jsonb_text_as_validation_error(api, monkeypatch):
    c, app, settings = api
    request = import_sample(c)
    monkeypatch.setattr(c._transport, "raise_server_exceptions", False)
    results = []
    for text in ("income\x00", "\ud800"):
        response = c.post(
            "/api/v1/tasks",
            content=json.dumps({**request, "question": text}),
            headers={"Idempotency-Key": uuid4().hex, "Content-Type": "application/json"},
        )
        results.append((response.status_code, response.json()["error"]["code"]))
    assert results == [(422, "WEB_VALIDATION"), (422, "WEB_VALIDATION")], results


@pytest.mark.integration
def test_corpus_listing_cap_must_not_revoke_existing_run_authority(api):
    c, app, settings = api
    request = import_sample(c)
    metric = request["metrics"][0]
    root = Path(__file__).resolve().parents[1]
    document = c.post(
        f"/api/v1/datasets/{metric['dataset_id']}/versions/1/documents",
        files={"file": ("billing.md", (root / "tests/fixtures/reporting/billing.md").read_bytes())},
        data={"reviewed": "true"},
    )
    assert document.status_code == 200, document.text
    corpus_id = document.json()["corpus_id"]
    assert UUID(corpus_id).int > 100
    request["documents"] = {
        "question": "paid invoice revenue",
        "metric_goals": [metric["goal_id"]],
        "corpus_ids": [corpus_id],
    }
    payload = run_async(app.state.service.task_payload(CreateTask.model_validate(request)))
    ack = app.state.store.command(uuid4().hex, "create", payload, payload=payload)
    run_async(app.state.service.authorize_run(ack["run_id"]))
    # Test-only PG metadata fillers. The target above is a real locally embedded corpus.
    for index in range(1, 101):
        target = Target(
            corpus_id=str(UUID(int=index)),
            owner=app.state.store.policy.owner,
            dataset_id=metric["dataset_id"],
            dataset_version=1,
        )
        app.state.store.corpus(
            target, CorpusPin(corpus_id=target.corpus_id, index_version="a" * 64, document_ids=[])
        )
    assert corpus_id not in {row["corpus_id"] for row in app.state.store.corpora()}
    # No grant, Dataset version, actual document or host policy was changed.
    run_async(app.state.service.authorize_run(ack["run_id"]))
    assert c.get(f"/api/v1/tasks/{ack['run_id']}/review").status_code == 200
    assert len(app.state.store.corpora(corpus_id=corpus_id)) == 1
    assert app.state.store.corpora(corpus_id=str(uuid4())) == []
    # Exact lookup must retain hash checks; damage only this test owner's new pin.
    with app.state.store.transaction() as conn:
        execute(
            conn,
            "UPDATE execution.web_corpora SET payload_hash=:h WHERE owner=:o AND corpus_id=:c",
            h="0" * 64,
            o=app.state.store.policy.owner,
            c=corpus_id,
        )
    with pytest.raises(AgentFailure):
        run_async(app.state.service.authorize_run(ack["run_id"]))
