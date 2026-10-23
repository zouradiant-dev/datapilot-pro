"""Streamlit/HTTP Mock interaction tests; not a database or browser E2E."""

from pathlib import Path
from uuid import uuid4

import httpx
from streamlit.testing.v1 import AppTest

from datapilot.web.client import APIClient


def test_chat_lost_message_ack_rerun_reconnect_and_safe_text(monkeypatch):
    cid, mid = str(uuid4()), str(uuid4())
    history, messages, keys = [], [], []

    def get(_, path):
        if path == "/health":
            return {"mode": "fake"}
        if path == "/conversations":
            return {"conversations": history}
        if path.startswith("/datasets?"):
            return {"datasets": [], "next_offset": None}
        if path == "/tasks":
            return {"run_ids": []}
        if "/messages?" in path:
            return {"messages": messages, "next_before": None}
        raise AssertionError(path)

    def post(_, path, body=None, *, key=None, **kwargs):
        if path == "/conversations":
            if not history:
                history.append({"conversation_id": cid, "created_at": "2026-10-23T12:00:00+08:00"})
            return history[0]
        assert path == f"/conversations/{cid}/messages" and key
        keys.append(key)
        if not messages:
            messages.append(
                {
                    "message_id": mid,
                    "sequence": 1,
                    "text": body["text"],
                    "upload_id": None,
                    "run_id": None,
                    "unavailable": False,
                    "draft": {"request": None, "missing": ["请确认业务映射"], "notes": []},
                }
            )
            raise httpx.ReadTimeout("Mock committed message, response lost")
        return messages[0]

    monkeypatch.setattr(APIClient, "__init__", lambda self: None)
    monkeypatch.setattr(APIClient, "get", get)
    monkeypatch.setattr(APIClient, "post", post)
    monkeypatch.setattr(APIClient, "close", lambda self: None)
    ui = AppTest.from_file(str(Path(__file__).parents[1] / "src/datapilot/web/ui.py"))
    ui.run(timeout=20)
    assert not ui.exception and ui.chat_input
    assert any("Fake" in x.value and "真实服务" in x.value for x in ui.info)
    text = '<script>alert("secret")</script> 分析2025年10月收入'
    ui.chat_input[0].set_value(text).run(timeout=20)
    assert not ui.exception
    key = ui.session_state["message_intent"]["key"]
    next(b for b in ui.button if b.label == "重新连接本地 API").click().run(timeout=20)
    assert ui.session_state["message_intent"]["key"] == key
    next(b for b in ui.button if b.label == "重试同一消息").click().run(timeout=20)
    assert not ui.exception and keys == [key, key] and len(messages) == 1
    assert any(x.value == text for x in ui.text)  # Plain text, never unsafe HTML/Markdown.
    ui.run(timeout=20)
    assert keys == [key, key]  # Rerender/history GET must not send another message.


def test_approval_ack_loss_uses_original_key_after_rerender(monkeypatch):
    id_, keys = str(uuid4()), []

    def get(_, path):
        if path.endswith("/review"):
            return {
                "request": {"question": "验证审批", "metrics": [], "require_review": True},
                "definitions": [],
                "dataset_names": [],
                "document_scope": [],
                "model_mode": "fake",
                "max_model_calls": 8,
                "max_tokens": 18000,
                "cost": "Fake",
            }
        return {
            "status": "awaiting_review",
            "business_completion": None,
            "question": "验证审批",
            "tasks": [],
            "error": None,
            "report_available": False,
        }

    def post(_, path, body=None, *, key=None):
        assert path.endswith("/approve") and body == {"confirmed": True}
        keys.append(key)
        if len(keys) == 1:
            raise httpx.ReadTimeout("Mock approval committed, ACK lost")
        return {"run_id": id_}

    monkeypatch.setattr(APIClient, "__init__", lambda self: None)
    monkeypatch.setattr(APIClient, "get", get)
    monkeypatch.setattr(APIClient, "post", post)
    source = (
        "import httpx\nfrom datapilot.web.client import APIClient\n"
        "from datapilot.web.ui_components import render_run, show_error\n"
        "try:\n    render_run(APIClient(), '" + id_ + "', prefix='approval-test')\n"
        "except httpx.HTTPError as exc:\n    show_error(exc)\n"
    )
    ui = AppTest.from_string(source).run(timeout=20)
    assert next(b for b in ui.button if b.label == "批准执行").disabled
    ui.checkbox[0].check().run(timeout=20)
    next(b for b in ui.button if b.label == "批准执行").click().run(timeout=20)
    ui.run(timeout=20)
    next(b for b in ui.button if b.label == "批准执行").click().run(timeout=20)
    assert not ui.exception and len(keys) == 2 and keys[0] == keys[1]


def test_partial_business_result_keeps_successful_execution_distinct(monkeypatch):
    def get(_, path):
        if path.endswith("/report"):
            return {
                "business_completion": {"status": "partial"},
                "facts": [],
                "citations": [],
                "charts": [],
                "missing_requirements": ["CAUSAL_EVIDENCE_MISSING"],
                "markdown": "指标已核实；原因未证实。",
            }
        return {
            "status": "partial",
            "execution_status": "succeeded",
            "business_completion": {"status": "partial"},
            "question": "原因分析",
            "tasks": [],
            "error": None,
            "report_available": True,
        }

    monkeypatch.setattr(APIClient, "__init__", lambda self: None)
    monkeypatch.setattr(APIClient, "get", get)
    ui = AppTest.from_string(
        "from datapilot.web.client import APIClient\n"
        "from datapilot.web.ui_components import render_run\n"
        "render_run(APIClient(),'mock-partial',prefix='partial-test')"
    ).run(timeout=20)
    assert not ui.exception
    assert any("succeeded" in m.value and "partial" in m.value for m in ui.markdown)
    assert any("并非完整业务分析" in w.value for w in ui.warning)
