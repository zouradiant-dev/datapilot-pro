"""Streamlit reruns and HTTP intent boundaries with an explicit Mock API, no PG/model."""

from uuid import uuid4

import httpx
from streamlit.testing.v1 import AppTest

from datapilot.web.client import APIClient


def test_streamlit_lost_ack_reconnect_retry_and_explicit_new_task(monkeypatch):
    id_ = str(uuid4())
    metric = {
        "dataset_id": id_,
        "dataset_version": 1,
        "semantic_version": 1,
        "metric_id": "paid_invoice_revenue",
        "metric_version": 1,
    }
    dataset = {
        "schema": {"dataset_id": id_, "version": 1, "name": "mock-ui-only"},
        "semantics": [],
        "metrics": [metric],
    }
    created, keys = [], []

    def get(_, path):
        if path == "/health":
            return {"mode": "fake"}
        if path.startswith("/datasets?"):
            return {"datasets": [dataset], "next_offset": None}
        if path == "/corpora":
            return {"corpora": []}
        if path == "/tasks":
            return {"run_ids": list(dict.fromkeys(created))}
        if path.endswith("/trace"):
            return {"calls": []}
        if path.startswith("/tasks/"):
            return {
                "question": "mock-ui-only",
                "requested_metrics": [metric],
                "status": "pending",
                "execution_status": None,
                "business_completion": None,
                "error": None,
                "tasks": [],
                "report_available": False,
            }
        raise AssertionError(path)

    def post(_, path, body=None, *, key=None, **kwargs):
        assert path == "/tasks" and key
        existing = next((created[i] for i, k in enumerate(keys) if k == key), str(uuid4()))
        keys.append(key)
        created.append(existing)
        if len(keys) == 1:
            raise httpx.ReadTimeout("mock backend committed, response lost")
        return {"run_id": existing}

    monkeypatch.setattr(APIClient, "__init__", lambda self: None)
    monkeypatch.setattr(APIClient, "get", get)
    monkeypatch.setattr(APIClient, "post", post)
    monkeypatch.setattr(APIClient, "close", lambda self: None)
    # The original management workflow remains accessible behind the new chat navigation.
    ui = AppTest.from_string(
        "from datapilot.web.client import APIClient\n"
        "from datapilot.web.ui_management import render_management\n"
        "from datapilot.web.ui_components import show_error\n"
        "import streamlit as st\n"
        "import httpx\n"
        "try:\n"
        "    render_management(APIClient())\n"
        "except httpx.HTTPError as exc:\n"
        "    show_error(exc)\n"
        "    st.button('重新连接本地 API')\n"
    )

    def click(label):
        button = next(b for b in ui.button if b.label == label)
        button.click().run(timeout=20)
        assert not ui.exception

    ui.run(timeout=20)
    click("创建持久分析任务")
    pending_key = ui.session_state["create_intent"]["key"]
    click("重新连接本地 API")
    assert ui.session_state["create_intent"]["key"] == pending_key
    click("重试同一创建请求")
    ui.run(timeout=20)
    assert keys == [pending_key, pending_key]
    assert created[0] == created[1]
    click("明确创建新的分析任务")
    click("创建持久分析任务")
    assert keys[2] != pending_key and created[2] != created[0]


def test_dispatcher_poll_circuit_breaker_is_bounded(monkeypatch):
    import asyncio
    from contextlib import suppress

    from datapilot.persistence.session import run_async
    from datapilot.web.worker import Dispatcher

    class Store:
        polls = 0

        def pending(self):
            self.polls += 1
            raise OSError("mock DB unavailable")

    async def scenario():
        dispatcher = Dispatcher(Store(), "unused")
        original_sleep = asyncio.sleep

        async def fast_sleep(seconds):
            if dispatcher.poll_failures >= 3:
                dispatcher.stopping = True
            await original_sleep(0)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)
        task = asyncio.create_task(dispatcher.run())
        await task
        with suppress(asyncio.CancelledError):
            await task
        assert dispatcher.store.polls == 3
        assert dispatcher.last_error == "WEB_DISPATCH_UNAVAILABLE"

    run_async(scenario())
