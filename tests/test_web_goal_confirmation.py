"""DTO and Streamlit interaction tests; Mock HTTP, not browser or real PG."""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from datapilot.web.chat_contracts import ChatLaunch, ChatSelection, GoalReject, MessageCreate
from datapilot.web.client import APIClient


def test_confirmation_dtos_never_accept_host_attestation_or_actor():
    for key in (
        "confirmation_ref",
        "goal_scope_attestation",
        "actor_session_hash",
        "completion_eligible",
    ):
        with pytest.raises(ValidationError):
            ChatLaunch.model_validate({"confirmed": True, key: "forged"})
    assert not ChatLaunch(confirmed=True).covers_original_goal
    assert MessageCreate(text="original").model_dump().get("supersedes") is None
    assert "required_source_ids" not in ChatSelection().model_dump()
    with pytest.raises(ValidationError):
        GoalReject(expected_version=0, expected_contract_sha256="0" * 64)
    with pytest.raises(ValidationError):
        ChatSelection(document_purpose="summary")
    with pytest.raises(ValidationError):
        MessageCreate(text="original", selection={"corpus_ids": [], "confirmation_ref": "fake"})


def pending_message():
    mid, cid, ds = str(uuid4()), str(uuid4()), str(uuid4())
    request = {
        "question": "仅总结指定规则，不证明完整材料集合。",
        "metrics": [],
        "documents": {
            "question": "仅总结指定规则，不证明完整材料集合。",
            "purpose": "summary",
            "corpus_ids": [cid],
            "metric_goals": [],
        },
        "require_review": True,
    }
    goal = {
        "contract_id": mid,
        "version": 1,
        "contract_sha256": "a" * 64,
        "original_question": request["question"],
        "status": "pending_confirmation",
        "expires_at": "2026-11-01T00:00:00Z",
        "review": {
            "request": request,
            "definitions": [],
            "model_mode": "fake",
            "max_model_calls": 8,
            "max_tokens": 18000,
            "cost": "Fake，不调用付费模型",
        },
        "datasets": [
            {"dataset_id": ds, "version": 1, "name": "公开数据", "source_sha256": "b" * 64}
        ],
        "sources": [
            {
                "source_id": "c" * 64,
                "name": "<script>规则.md</script>",
                "required": True,
                "index_version": "d" * 64,
            }
        ],
        "limitations": ["用户确认范围不是业务事实验证", "不证明全语料无遗漏"],
        "unresolved": [],
        "can_confirm": True,
    }
    return {
        "message_id": mid,
        "text": request["question"],
        "run_id": None,
        "upload_id": None,
        "unavailable": False,
        "draft": {"request": request, "missing": []},
        "goal_contract": goal,
    }


def test_ui_pending_reload_requires_three_explicit_decisions_and_preserves_original(monkeypatch):
    m = pending_message()
    cid = str(uuid4())
    calls = []

    def get(_, path):
        if path == "/health":
            return {"mode": "fake"}
        if path == "/conversations":
            return {"conversations": [{"conversation_id": cid, "created_at": "2026-10-31"}]}
        if path.startswith("/datasets?"):
            return {"datasets": [], "next_offset": None}
        if path == "/tasks":
            return {"run_ids": []}
        if "/messages?" in path:
            return {"messages": [deepcopy(m)], "next_before": None}
        raise AssertionError(path)

    def post(_, path, body=None, *, key=None, **kwargs):
        calls.append((path, body, key))
        assert path.endswith("/launch")
        m["goal_contract"]["status"] = "confirmed"
        return {"run_id": str(uuid4())}

    monkeypatch.setattr(APIClient, "__init__", lambda self: None)
    monkeypatch.setattr(APIClient, "get", get)
    monkeypatch.setattr(APIClient, "post", post)
    ui = AppTest.from_file(str(Path(__file__).parents[1] / "src/datapilot/web/ui.py"))
    ui.query_params["conversation"] = cid
    ui.run(timeout=20)
    assert not ui.exception and calls == []

    def confirm():
        return next(b for b in ui.button if b.label == "确认范围并创建待审批任务")

    assert confirm().disabled
    assert sum(c.value is False for c in ui.checkbox) >= 3
    assert any(t.value == m["text"] for t in ui.text)
    assert any("<script>" in t.value for t in ui.text)  # Escaped/plain text source names.
    for suffix in ("reviewed", "covered", "resolved"):
        next(c for c in ui.checkbox if c.key.endswith("-" + suffix)).check().run(timeout=20)
    assert not confirm().disabled and calls == []
    confirm().click().run(timeout=20)
    assert not ui.exception and len(calls) == 1
    body = calls[0][1]
    assert body["expected_contract_sha256"] == "a" * 64 and body["covers_original_goal"] is True
    assert not {"confirmation_ref", "goal_scope_attestation", "actor_session_hash"} & body.keys()
    ui.run(timeout=20)
    assert len(calls) == 1  # A read/rerender never repeats confirmation.


def test_legacy_host_hash_stays_stable_until_profile_is_explicit():
    from datapilot.config import Settings
    from datapilot.web.config import HostPolicy
    from datapilot.web.store import WebStore

    policy = HostPolicy(secret="public-test", owner="test", data_dir=Path("."))
    store = object.__new__(WebStore)
    store.policy = policy
    settings = Settings(_env_file=None, llm_mode="fake")
    original = store.host_settings_hash(settings)
    assert store.host_settings_hash(settings) == original
    store.policy = policy.model_copy(update={"rag_embedding_profile": "qwen3-cuda-fp16-v1"})
    assert store.host_settings_hash(settings) != original


@pytest.mark.parametrize(
    "code", ["GOAL_INPUT_LIMIT", "GOAL_SOURCE_QUOTA", "GOAL_SIZE", "WEB_SCOPE"]
)
def test_ui_can_edit_after_a_definite_precommit_goal_limit(code):
    ui = AppTest.from_string(
        "import streamlit as st\n"
        "from datapilot.web.ui_chat import append\n"
        "from datapilot.web.client import ClientError\n"
        "class API:\n"
        f" def post(self,*args,**kwargs): raise ClientError({{'code':'{code}'}})\n"
        "try: append(API(),'public-test',{'text':'too long'})\n"
        "except ClientError: pass\n"
        "st.write('message_intent' in st.session_state)\n"
    ).run()
    assert not ui.exception and "message_intent" not in ui.session_state


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["文档", "billing.md中的", "rules.txt中的"])
async def test_explicit_document_goal_cannot_silently_become_metric_only(reference):
    from datapilot.contracts import AgentFailure
    from datapilot.web.contracts import CreateTask
    from datapilot.web.service import ProductService

    request = CreateTask.model_validate_json(
        __import__("json").dumps(
            {
                "question": f"计算2025年10月已支付账单收入并引用{reference}说明规则。",
                "metrics": [
                    {
                        "goal_id": "income",
                        "dataset_id": str(uuid4()),
                        "dataset_version": 1,
                        "semantic_version": 1,
                        "metric_id": "paid_invoice_revenue",
                        "metric_version": 1,
                        "window": {"start": "2025-10-01", "end_exclusive": "2025-11-01"},
                    }
                ],
            }
        )
    )
    with pytest.raises(AgentFailure, match="文档") as exc:
        await ProductService.task_payload(object(), request)
    assert exc.value.error.code == "DOCUMENT_SCOPE_REQUIRED"
