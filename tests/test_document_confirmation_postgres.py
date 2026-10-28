"""Real HTTP/PG/MCP/embedding/Journal; model decisions are explicitly scripted."""

from uuid import uuid4

import pytest
from test_cross_source_postgres import ReportDecisions
from test_web_postgres import api as api
from test_web_postgres import import_sample

from datapilot.persistence.session import run_async
from datapilot.web.worker import execute_one

pytestmark = pytest.mark.integration
QUESTION = "根据已授权文档，说明已支付账单收入的口径。"


def post(client, path, body):
    return client.post(path, json=body, headers={"Idempotency-Key": uuid4().hex})


def document(client):
    request = import_sample(client)
    metric = request["metrics"][0]
    path = f"/api/v1/datasets/{metric['dataset_id']}/versions/{metric['dataset_version']}/documents"
    response = client.post(
        path,
        files={"file": ("policy.md", "已支付账单收入按付款时间统计，仅计入 paid 账单。".encode())},
        data={"reviewed": "true"},
    )
    assert response.status_code == 200, response.text
    return {
        "dataset_id": metric["dataset_id"],
        "dataset_version": metric["dataset_version"],
        "corpus_ids": [response.json()["corpus_id"]],
    }


@pytest.mark.parametrize(
    "purpose,expected",
    [
        ("locate", "completed"),
        ("summary", "completed"),
        ("facts", "unavailable"),
        ("conclusion", "partial"),
    ],
)
def test_confirmed_document_purpose_survives_chat_review_and_durable(api, purpose, expected):
    c, app, settings = api
    selection = document(c)
    cid = post(c, "/api/v1/conversations", {}).json()["conversation_id"]
    path = f"/api/v1/conversations/{cid}/messages"
    first = post(c, path, {"text": QUESTION, "selection": selection})
    assert first.status_code == 200, first.text
    assert first.json()["draft"]["request"] is None and first.json()["draft"]["missing"]
    selection["document_purpose"] = purpose
    if purpose == "facts":
        selection["required_facts"] = [{"fact_id": "rule", "description": "收入规则"}]
    response = post(c, path, {"text": QUESTION, "selection": selection})
    assert response.status_code == 200, response.text
    message = response.json()
    mid = message["message_id"]
    assert message["draft"]["request"]["documents"]["purpose"] == purpose
    launch = f"{path}/{mid}/launch"
    response = post(c, launch, {"confirmed": True})
    assert response.status_code == 200, response.text
    rid = response.json()["run_id"]
    assert post(c, launch, {"confirmed": True}).json()["run_id"] == rid
    run_async(execute_one(settings, app.state.store, rid, transport=ReportDecisions(QUESTION)))
    assert c.get(f"/api/v1/tasks/{rid}").json()["status"] == "awaiting_review"
    response = post(c, f"/api/v1/tasks/{rid}/approve", {"confirmed": True})
    assert response.status_code == 200, response.text
    run_async(execute_one(settings, app.state.store, rid, transport=ReportDecisions(QUESTION)))
    report = c.get(f"/api/v1/tasks/{rid}/report")
    assert report.status_code == 200, report.text
    assert report.json()["business_completion"]["status"] == expected
    assert not report.json()["facts"] and not report.json()["charts"]
    before = app.state.store.run(rid)["payload_hash"]
    selection["document_purpose"] = "summary" if purpose != "summary" else "locate"
    selection.pop("required_facts", None)
    follow = post(c, path, {"text": QUESTION, "selection": selection}).json()
    other = post(c, f"{path}/{follow['message_id']}/launch", {"confirmed": True}).json()
    assert other["run_id"] != rid and app.state.store.run(rid)["payload_hash"] == before
    history = c.get(path).json()["messages"]
    assert (
        next(m for m in history if m["message_id"] == mid)["draft"]["request"]["documents"][
            "purpose"
        ]
        == purpose
    )
    assert c.get(f"/api/v1/tasks/{rid}/report").json() == report.json()


def test_legacy_creation_and_source_injection_do_not_grant_confirmation(api):
    c, app, _ = api
    selection = document(c)
    body = {
        "question": QUESTION,
        "metrics": [],
        "documents": {
            "question": QUESTION,
            "metric_goals": [],
            "corpus_ids": selection["corpus_ids"],
        },
    }
    response = post(c, "/api/v1/tasks", body)
    assert response.status_code >= 400
    assert response.json()["error"]["code"] == "DOCUMENT_CONFIRMATION_REQUIRED"
    assert c.get("/api/v1/tasks").json()["run_ids"] == []
    body["documents"].update(purpose="summary", corpus_ids=[str(uuid4())])
    response = post(c, "/api/v1/tasks", body)
    assert response.status_code >= 400 and response.json()["error"]["code"] == "WEB_SCOPE"
    body["documents"]["document_ids"] = ["a" * 64]
    assert post(c, "/api/v1/tasks", body).status_code == 422
