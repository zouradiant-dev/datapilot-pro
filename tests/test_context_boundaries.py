"""Native HTTP mock protocol and genuine P3 verifier outputs preserved by P5A views."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from langchain_openai import ChatOpenAI
from test_context_engineering import ModelDouble, history, make_context, memory_entry
from test_semantics import execution_case
from test_semantics import semantic_case as semantic_case

from datapilot.contracts import AgentFailure
from datapilot.harness.metric_verification import make_evidence, verify_execution
from datapilot.orchestration.context import closed_batches
from datapilot.orchestration.context_contracts import (
    ContextScope,
    MetricBinding,
    P3Reference,
    SourcePin,
)
from datapilot.orchestration.memory import InMemoryMemoryStore
from datapilot.orchestration.model import NativeTransport


async def test_native_async_http_summary_tool_pairing_and_usage(settings):
    requests = []

    async def respond(request):
        raw = json.loads(request.content)
        requests.append(raw)
        if raw["messages"][0]["content"].startswith("CONTEXT_SUMMARY_JSON"):
            content = json.loads(raw["messages"][-1]["content"])["expected"]
            content["decisions"] = ["turn_0"]
        else:
            # Latest provider batch remains a complete assistant/tool pair after L4.
            assert raw["messages"][-1]["role"] == "tool"
            assert raw["messages"][-2]["tool_calls"][0]["id"] == raw["messages"][-1]["tool_call_id"]
            content = {
                "artifact_ids": [
                    json.loads(raw["messages"][-1]["content"])["artifact_refs"][0]["artifact_id"]
                ]
            }
        return httpx.Response(
            200,
            json={
                "id": "mock",
                "object": "chat.completion",
                "created": 0,
                "model": "fixture",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(content)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        chat = ChatOpenAI(
            model="fixture",
            api_key="mock-only",
            base_url="https://model.invalid/v1",
            http_async_client=http,
            max_retries=0,
            stream_usage=False,
        )
        _, manager, gateway, registry, prefix = make_context(settings, max_chars=7100)
        gateway.transport = NativeTransport(chat)
        await gateway.invoke(
            history(manager, prefix, count=4, ai_body=1800, body=900), registry.schemas(), "1:r"
        )
    assert len(requests) == 2 and gateway.ledger.snapshot().reported_tokens == 60
    assert manager.stats[-1].summary_reported_tokens == 30
    assert "tools" not in requests[0] and {t["function"]["name"] for t in requests[1]["tools"]} == {
        "search_documents",
        "read_context",
    }
    assert all("cache_control" not in json.dumps(r) for r in requests)
    assert not gateway.ledger.pending


@pytest.fixture
def pins(semantic_case):
    context, request = semantic_case()
    execution = execution_case(context, request)
    evidence = make_evidence(execution)
    record = verify_execution(execution, evidence, evidence)
    assert record.verdict == "verified"
    scope = ContextScope(
        profile="dataset",
        sources=(
            SourcePin(
                dataset_id=context.dataset_id,
                version=context.dataset_version,
                source_sha256=context.source_sha256,
            ),
        ),
    )
    return (
        scope,
        MetricBinding(request=request, context=context),
        P3Reference.from_verified(evidence, record),
    )


async def test_p3_verified_refs_metric_units_versions_and_time_window_survive_l4(settings, pins):
    scope, binding, reference = pins
    _, manager, gateway, registry, prefix = make_context(
        settings,
        max_chars=20000,
        max_tokens=40000,
        scope=scope,
        metadata={"metrics": (binding,), "p3_verified_refs": (reference,)},
    )
    before = manager.authority.model_dump_json()
    await gateway.invoke(
        history(manager, prefix, count=4, ai_body=9000, body=900), registry.schemas(), "1:r"
    )
    assert manager.stats[-1].levels[-1] == "L4"
    view = gateway.transport.requests[-1]
    summary = json.loads(next(m.content for m in view if m.name == "context_summary"))
    assert summary["metrics"][0] == binding.model_dump(mode="json")
    assert summary["metrics"][0]["context"]["definition"]["currency"] == "CNY"
    assert summary["metrics"][0]["request"]["window"]["end_exclusive"] == "2025-11-01"
    assert summary["p3_verified_refs"][0] == reference.model_dump(mode="json")
    assert manager.authority.model_dump_json() == before and len(closed_batches(view)) == 1


@pytest.mark.parametrize("part", ["source", "metric_version", "unit", "window", "p3_reference"])
async def test_summary_cannot_redefine_pinned_business_semantics(settings, pins, part):
    scope, binding, reference = pins

    def mutate(c):
        if part == "source":
            c["scope"]["sources"][0]["version"] = 2
        elif part == "metric_version":
            c["metrics"][0]["request"]["metric_version"] = 2
        elif part == "unit":
            c["metrics"][0]["context"]["definition"]["currency"] = "USD"
        elif part == "window":
            c["metrics"][0]["request"]["window"]["end_exclusive"] = "2025-10-31"
        else:
            c["p3_verified_refs"][0]["verification_sha256"] = "0" * 64

    _, manager, gateway, registry, prefix = make_context(
        settings,
        max_chars=20000,
        max_tokens=40000,
        scope=scope,
        metadata={"metrics": (binding,), "p3_verified_refs": (reference,)},
        model=ModelDouble(mutate),
    )
    with pytest.raises(AgentFailure) as caught:
        await gateway.invoke(
            history(manager, prefix, count=4, ai_body=9000, body=900), registry.schemas(), "1:r"
        )
    assert caught.value.error.code == "CONTEXT_LIMIT" and not gateway.ledger.pending
    assert len(gateway.transport.requests) == 1


async def test_memory_invalidation_and_source_freshness_are_checked_each_model_view(settings):
    _, manager, gateway, registry, prefix = make_context(settings, max_chars=64000)
    now = datetime.now(UTC)
    entry = memory_entry(
        worker="rag", created_at=now - timedelta(hours=1), expires_at=now + timedelta(hours=1)
    )
    store = InMemoryMemoryStore()
    store.put_reviewed(entry, reviewed=True)
    versions = {entry.source_ref: entry.source_version}
    manager.memory_loader = lambda: store.recall(
        manager.authority.scope, "rag", now=datetime.now(UTC), source_versions=versions
    )
    await gateway.invoke(prefix, registry.schemas(), "1:r")
    anchor = json.loads(gateway.transport.requests[-1][-1].content)
    assert anchor["reviewed_hints_not_authority"] == [entry.hint.model_dump()]
    versions[entry.source_ref] = "2"
    await gateway.invoke(prefix, registry.schemas(), "1:r")
    assert gateway.transport.requests[-1] == prefix
    versions[entry.source_ref] = "1"
    store.invalidate(entry.memory_id, reason="source_changed", at=datetime.now(UTC))
    await gateway.invoke(prefix, registry.schemas(), "1:r")
    assert gateway.transport.requests[-1] == prefix and not gateway.ledger.pending
