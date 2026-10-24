"""Real SDK HTTP mocks, plus an explicitly separate real PostgreSQL/MCP case."""

import asyncio
import json
from functools import partial

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from datapilot.config import Settings
from datapilot.contracts import AgentFailure, RouteDecision
from datapilot.graph import run_question
from datapilot.harness.budget import RunBudget
from datapilot.llm import provider
from datapilot.llm.client import create_live_client
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.contracts import BudgetLimits
from datapilot.orchestration.model import Gateway, live_transport
from datapilot.orchestration.runtime import Cancellation

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_database",
            "parameters": {
                "type": "object",
                "properties": {"sql": {"type": "string"}},
                "required": ["sql"],
            },
        },
    }
]
MESSAGES = [SystemMessage(content="Return JSON only."), HumanMessage(content="Count customers")]


def config(**overrides):
    values = {
        "llm_mode": "live",
        "model_provider": "deepseek",
        "model": "deepseek-flash",
        "base_url": "https://api.deepseek.com",
        "api_key": "mock-only",
        "reader_database_url": None,
        "upload_reader_database_url": None,
    }
    return Settings(**(values | overrides), _env_file=None)


def completion(message, *, usage=True):
    body = {
        "id": "mock-deepseek",
        "object": "chat.completion",
        "created": 0,
        "model": "deepseek-flash",
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
    }
    if usage:
        body["usage"] = {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}
    return httpx.Response(200, json=body)


def reply_to_tool(request):
    raw = json.loads(request.content)
    if raw["messages"][-1]["role"] == "tool":
        tool = raw["messages"][-1]
        assert raw["messages"][-2]["tool_calls"][0]["id"] == tool["tool_call_id"]
        ref = json.loads(tool["content"])["artifact_refs"][0]["artifact_id"]
        return completion({"role": "assistant", "content": json.dumps({"artifact_ids": [ref]})})
    return completion(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "ds-query",
                    "type": "function",
                    "function": {
                        "name": "query_database",
                        "arguments": '{"sql":"SELECT COUNT(*) AS n FROM customers"}',
                    },
                }
            ],
        }
    )


def gateway(settings):
    return Gateway(
        live_transport(settings),
        settings,
        BudgetLedger(BudgetLimits(calls=8, tokens=18000)),
        Cancellation(),
    )


async def test_deepseek_document_id_native_argument_is_preserved(monkeypatch):
    from datapilot.orchestration.tools import DEFINITIONS

    args = {"artifact_id": "a" * 64, "document_id": "actual-authorized-document", "max_chars": 512}

    async def respond(request):
        raw = json.loads(request.content)
        assert "document_id" in raw["tools"][0]["function"]["parameters"]["properties"]
        return completion(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "native-document-read",
                        "type": "function",
                        "function": {"name": "read_context", "arguments": json.dumps(args)},
                    }
                ],
            }
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        monkeypatch.setattr(provider, "ChatOpenAI", partial(ChatOpenAI, http_async_client=http))
        response = await gateway(config()).invoke(
            MESSAGES, [DEFINITIONS["read_context"].schema()], "root"
        )
    assert response.tool_calls[0]["args"] == args


@pytest.mark.parametrize("base_url", ["https://api.deepseek.com", "https://api.deepseek.com/v1"])
async def test_deepseek_native_payload_and_tool_roundtrip(monkeypatch, base_url):
    requests = []

    async def respond(request):
        assert request.url.path in ("/chat/completions", "/v1/chat/completions")
        raw = json.loads(request.content)
        requests.append(raw)
        assert raw["model"] == "deepseek-flash" and raw["max_tokens"] == 1200
        assert raw["thinking"] == {"type": "disabled"}
        assert (
            not {"max_completion_tokens", "extra_body", "reasoning_effort", "stream_options"}
            & raw.keys()
        )
        assert raw["tools"] == TOOLS and raw["stream"] is False
        return reply_to_tool(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        monkeypatch.setattr(provider, "ChatOpenAI", partial(ChatOpenAI, http_async_client=http))
        model = gateway(config(base_url=base_url))
        assistant = await model.invoke(MESSAGES, TOOLS, "root")
        assert assistant.content == "" and assistant.tool_calls[0]["id"] == "ds-query"
        tool = ToolMessage(
            content='{"artifact_refs":[{"artifact_id":"fixture-ref"}]}',
            tool_call_id="ds-query",
            name="query_database",
        )
        final = await model.invoke([*MESSAGES, assistant, tool], TOOLS, "root")
    assert json.loads(final.content) == {"artifact_ids": ["fixture-ref"]}
    assert len(requests) == 2 and model.ledger.snapshot().reported_tokens == 60
    assert not model.ledger.pending


async def test_deepseek_planner_without_tools(monkeypatch):
    async def respond(request):
        raw = json.loads(request.content)
        assert "tools" not in raw and raw["thinking"] == {"type": "disabled"}
        return completion({"role": "assistant", "content": '{"tasks":[],"unsupported":true}'})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        monkeypatch.setattr(provider, "ChatOpenAI", partial(ChatOpenAI, http_async_client=http))
        model = gateway(config())
        assert (await model.plan("Unsupported fixture", {"sql"})).unsupported
    assert model.ledger.snapshot().calls == 1


def test_legacy_json_client_uses_same_deepseek_profile(monkeypatch):
    def respond(request):
        raw = json.loads(request.content)
        assert raw["max_tokens"] == 1200 and "max_completion_tokens" not in raw
        assert raw["thinking"] == {"type": "disabled"} and "tools" not in raw
        return completion({"role": "assistant", "content": '{"route":"sql"}'})

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        monkeypatch.setattr(provider, "ChatOpenAI", partial(ChatOpenAI, http_client=http))
        budget = RunBudget(2, 18000)
        client = create_live_client(config(), budget)
        assert client.generate(RouteDecision, system="Route", user="Count").route == "sql"
        assert budget.reported_tokens == 30


@pytest.mark.parametrize("status", [401, 429, 500])
async def test_deepseek_errors_are_redacted_charged_and_not_sdk_retried(monkeypatch, status):
    requests = []

    async def respond(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"message": "private-provider-detail"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        monkeypatch.setattr(provider, "ChatOpenAI", partial(ChatOpenAI, http_async_client=http))
        model = gateway(config())
        with pytest.raises(AgentFailure) as exc:
            await model.invoke(MESSAGES, [], "root")
    assert exc.value.error.code == "MODEL_ERROR"
    assert "private-provider-detail" not in exc.value.error.message
    assert len(requests) == 1 and model.ledger.snapshot().calls == 1
    assert model.ledger.snapshot().total_tokens > 0
    assert not model.ledger.snapshot().usage_complete and not model.ledger.pending


async def test_deepseek_timeout_cancels_native_http_and_keeps_reservation(monkeypatch):
    cancelled = asyncio.Event()

    async def respond(request):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        monkeypatch.setattr(provider, "ChatOpenAI", partial(ChatOpenAI, http_async_client=http))
        model = gateway(config(model_timeout_seconds=0.05))
        with pytest.raises(AgentFailure) as exc:
            await model.invoke(MESSAGES, [], "root")
    assert exc.value.error.code == "MODEL_TIMEOUT" and cancelled.is_set()
    assert not model.ledger.snapshot().usage_complete and not model.ledger.pending


async def test_generic_openai_profile_payload_is_unchanged(monkeypatch):
    async def respond(request):
        raw = json.loads(request.content)
        assert raw["max_completion_tokens"] == 1200
        assert "thinking" not in raw and "max_tokens" not in raw
        return completion({"role": "assistant", "content": "{}"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        monkeypatch.setattr(provider, "ChatOpenAI", partial(ChatOpenAI, http_async_client=http))
        await gateway(config(model_provider="openai_compatible", model="fixture")).invoke(
            MESSAGES, [], "root"
        )


def test_provider_is_explicit_and_credentials_have_no_fake_fallback():
    with pytest.raises(ValidationError):
        config(model_provider="invented")
    with pytest.raises(ValidationError):
        config(api_key=None)


@pytest.mark.integration
async def test_deepseek_http_mock_with_real_postgres_mcp(monkeypatch, pg_settings):
    requests = []

    async def respond(request):
        requests.append(json.loads(request.content))
        return reply_to_tool(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        monkeypatch.setattr(provider, "ChatOpenAI", partial(ChatOpenAI, http_async_client=http))
        settings = config(reader_database_url=pg_settings.reader_database_url)
        result = await run_question(settings, "查询客户总数")
    assert result["status"] == "succeeded", result["error"]
    assert result["completion"].status == "completed"
    assert result["result"].result.rows == [[240]] and len(requests) == 2
    assert result["usage"]["reported_tokens"] == 60
    assert all(raw["thinking"] == {"type": "disabled"} for raw in requests)
