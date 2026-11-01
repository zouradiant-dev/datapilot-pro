"""Real HTTP/PG/MCP/embedding/Journal; model decisions are explicitly scripted."""

from uuid import uuid4

import pytest
from test_cross_source_postgres import ReportDecisions
from test_web_goal_confirmation_postgres import decision
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
    # Purpose selection is not Goal v4 approval. Review this exact public synthetic
    # contract through the real HTTP actor/event path, then approve execution separately.
    assert message["goal_contract"]["status"] == "pending_confirmation"
    assert message["text"] == message["goal_contract"]["original_question"] == QUESTION
    assert message["goal_contract"]["can_confirm"] and not message["goal_contract"]["unresolved"]
    assert message["goal_contract"]["review"]["request"]["documents"]["purpose"] == purpose
    assert post(c, launch, {"confirmed": True}).status_code == 403
    response = post(c, launch, decision(message))
    assert response.status_code == 200, response.text
    rid = response.json()["run_id"]
    assert post(c, launch, decision(message)).json()["run_id"] == rid
    payload = app.state.store.run(rid)["payload"]
    assert payload["report_scope"]["goal_scope_attestation"]["confirmation_ref"] == (
        "web-goal:" + payload["goal_confirmation"]["event_id"]
    )
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
    other = post(c, f"{path}/{follow['message_id']}/launch", decision(follow)).json()
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
    from test_chat_postgres import conversation

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
    assert response.json()["error"]["code"] == "GOAL_CONFIRMATION_REQUIRED"
    assert c.get("/api/v1/tasks").json()["run_ids"] == []
    body["documents"].update(purpose="summary", corpus_ids=[str(uuid4())])
    response = post(c, "/api/v1/tasks", body)
    assert response.status_code >= 400
    assert response.json()["error"]["code"] == "GOAL_CONFIRMATION_REQUIRED"
    # Exercise the actual source authorization guard through the current proposal API;
    # the legacy entry point must not mint confirmation even when purpose is supplied.
    cid = conversation(c)
    response = post(
        c,
        f"/api/v1/conversations/{cid}/messages",
        {
            "text": QUESTION,
            "selection": {
                **selection,
                "document_purpose": "summary",
                "corpus_ids": body["documents"]["corpus_ids"],
            },
        },
    )
    assert response.status_code >= 400 and response.json()["error"]["code"] == "WEB_SCOPE"
    body["documents"]["document_ids"] = ["a" * 64]
    assert post(c, "/api/v1/tasks", body).status_code == 422
    assert c.get("/api/v1/tasks").json()["run_ids"] == []
