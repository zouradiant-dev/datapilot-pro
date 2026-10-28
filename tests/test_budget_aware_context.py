"""Independent synthetic budget-pressure inputs; no historical Holdout or paid model."""

import asyncio
import json
from functools import partial

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage, messages_to_dict
from langchain_openai import ChatOpenAI
from test_context_engineering import ModelDouble, history, make_context

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.llm import provider
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.context import closed_batches, measure_context
from datapilot.orchestration.contracts import BudgetLimits
from datapilot.orchestration.model import live_transport


def prepared_case(settings, *, pressure="root", body=1200, ai_body=0, available=None, model=None):
    config, manager, gateway, registry, prefix = make_context(
        settings, max_chars=64000, max_tokens=100000, keep=1, model=model
    )
    messages = history(manager, prefix, count=4, body=body, ai_body=ai_body)
    need = measure_context(messages, registry.schemas(), config.max_output_tokens)[1]
    required = need.estimated_input_tokens + need.output_reserved_tokens
    assert required < 18000
    amount = available if available is not None else required - 900
    limits = BudgetLimits(calls=8, tokens=18000)
    child = BudgetLimits(calls=8, tokens=amount if pressure == "child" else 18000)
    ledger = BudgetLedger(limits)
    ledger.fork("1:r", child)
    ledger.fork("peer", limits)
    if pressure in {"root", "pending"}:
        ticket = ledger.reserve_batch("peer", [(0, 18000 - amount)])[0]
        if pressure != "pending":
            ledger.settle(ticket, 18000 - amount)
    gateway.ledger = ledger
    registry.envelope.budget = child
    return manager, gateway, registry, messages, required


@pytest.mark.parametrize("pressure", ["root", "child", "pending"])
async def test_budget_pressure_compacts_below_window_before_original_reservation(
    settings, pressure
):
    manager, gateway, registry, messages, required = prepared_case(settings, pressure=pressure)
    canonical = messages_to_dict(messages)
    schema = registry.schemas()
    assert manager.fits(messages, schema, ratio=manager.limits.trigger_ratio)
    pending = dict(gateway.ledger.pending)
    await gateway.invoke(messages, schema, "1:r")
    assert manager.stats and manager.stats[-1].levels
    assert manager.stats[-1].after_estimated_tokens + manager.limits.output_tokens < required
    assert gateway.ledger.snapshot("1:r").calls == 1
    assert gateway.ledger.snapshot("1:r").reported_tokens == 30
    assert gateway.ledger.pending == pending
    assert messages_to_dict(messages) == canonical
    assert closed_batches(gateway.transport.requests[-1])


def test_latest_snapshot_and_budget_are_separate_host_failures():
    from datapilot.orchestration.rag_completion import retrieval_goal

    goal = retrieval_goal("基于宿主已固定的最新快照检索经营规则，分析跨来源资料。")
    assert goal["unsupported_requirements"] is True
    assert goal["unsupported_reason"] == "snapshot_not_attested"


async def test_ample_parent_and_child_leave_view_and_ledger_policy_unchanged(settings):
    manager, gateway, registry, messages, _ = prepared_case(settings, pressure="none")
    canonical = messages_to_dict(messages)
    limits = {k: a.limits.model_dump() for k, a in gateway.ledger.accounts.items()}
    await gateway.invoke(messages, registry.schemas(), "1:r")
    assert not manager.stats and messages_to_dict(gateway.transport.requests[0]) == canonical
    assert {k: a.limits.model_dump() for k, a in gateway.ledger.accounts.items()} == limits


async def test_budget_pressure_can_require_l3_even_when_window_is_ample(settings):
    manager, gateway, registry, messages, _ = prepared_case(settings, ai_body=500, body=600)
    current = gateway.ledger.snapshot().total_tokens
    ticket = gateway.ledger.reserve_batch("peer", [(0, 1500)])[0]
    gateway.ledger.settle(ticket, 1500)
    await gateway.invoke(messages, registry.schemas(), "1:r")
    assert "L3" in manager.stats[-1].levels
    assert manager.stats[-1].summary_calls == 0
    assert gateway.ledger.snapshot().total_tokens == current + 1500 + 30


@pytest.mark.parametrize("enabled", [True, False])
async def test_cannot_fit_protected_context_never_calls_or_releases_other_reservations(
    settings, enabled
):
    config = settings.model_copy(update={"context_compression": enabled})
    manager, gateway, registry, messages, _ = prepared_case(config, available=150)
    before = gateway.ledger.dump_state()
    canonical = messages_to_dict(messages)
    with pytest.raises(AgentFailure) as exc:
        await gateway.invoke(messages, registry.schemas(), "1:r")
    assert exc.value.error.code == "BUDGET_EXCEEDED"
    assert not gateway.transport.requests and gateway.ledger.dump_state() == before
    assert messages_to_dict(messages) == canonical
    assert manager.authority.goals and manager.prefix == messages[: len(manager.prefix)]


async def test_no_eligible_history_refuses_without_new_archive_or_model(settings):
    manager, gateway, registry, messages, _ = prepared_case(settings, available=150)
    initial = messages[: len(manager.prefix)]
    old = gateway.ledger.dump_state()
    archives = len(registry.context_refs)
    with pytest.raises(AgentFailure) as exc:
        await gateway.invoke(initial, registry.schemas(), "1:r")
    assert exc.value.error.code == "BUDGET_EXCEEDED"
    assert gateway.ledger.dump_state() == old and len(registry.context_refs) == archives
    assert not gateway.transport.requests


async def test_repeated_compaction_uses_one_reservation_per_actual_call(settings):
    manager, gateway, registry, messages, _ = prepared_case(settings)
    before = gateway.ledger.snapshot()
    await gateway.invoke(messages, registry.schemas(), "1:r")
    await gateway.invoke(messages, registry.schemas(), "1:r")
    assert gateway.ledger.snapshot().calls == before.calls + 2
    assert gateway.ledger.snapshot().total_tokens == before.total_tokens + 60
    assert not gateway.ledger.pending
    assert all(s.summary_calls == 0 and not s.irreversible_source_loss for s in manager.stats)


@pytest.mark.parametrize("kind", ["unknown_usage", "negative_usage", "noninteger_usage", "timeout"])
async def test_unknown_outcome_after_budget_compaction_keeps_conservative_charge(settings, kind):
    class Timeout(ModelDouble):
        async def respond(self, messages, tools):
            self.requests.append(list(messages))
            await asyncio.sleep(1)

    class InvalidUsage(ModelDouble):
        async def respond(self, messages, tools):
            result = await super().respond(messages, tools)
            result.usage_metadata["total_tokens"] = -1 if kind == "negative_usage" else "30"
            return result

    model = (
        Timeout()
        if kind == "timeout"
        else ModelDouble(unknown=True)
        if kind == "unknown_usage"
        else InvalidUsage()
    )
    config = settings.model_copy(update={"model_timeout_seconds": 0.01})
    manager, gateway, registry, messages, _ = prepared_case(config, model=model)
    spent = gateway.ledger.snapshot().total_tokens
    if kind == "timeout":
        with pytest.raises(AgentFailure) as exc:
            await gateway.invoke(messages, registry.schemas(), "1:r")
        assert exc.value.error.code == "MODEL_TIMEOUT"
    else:
        await gateway.invoke(messages, registry.schemas(), "1:r")
    sent = measure_context(model.requests[0], registry.schemas(), manager.limits.output_tokens)[1]
    assert (
        gateway.ledger.snapshot().total_tokens
        == spent + sent.estimated_input_tokens + sent.output_reserved_tokens
    )
    assert not gateway.ledger.snapshot().usage_complete and not gateway.ledger.pending


def test_remaining_counts_all_ancestors_and_pending_without_mutation():
    ledger = BudgetLedger(BudgetLimits(calls=4, tokens=9000))
    ledger.fork("a", BudgetLimits(calls=3, tokens=6000))
    ledger.fork("b", BudgetLimits(calls=3, tokens=5000))
    held = ledger.reserve_batch("b", [(3000, 1000)])[0]
    state = ledger.dump_state()
    assert ledger.remaining("a") == (3, 5000)
    assert ledger.remaining("b") == (2, 1000)
    assert ledger.dump_state() == state
    ledger.release_unissued(held)
    assert ledger.remaining("a") == (3, 6000)
    with pytest.raises(AgentFailure):
        ledger.remaining("unknown")


async def test_budget_race_after_prepare_is_still_stopped_by_original_atomic_reserve(settings):
    manager, gateway, registry, messages, _ = prepared_case(settings, pressure="none")
    original = manager.prepare

    async def race(*args, **kwargs):
        result = await original(*args, **kwargs)
        ticket = gateway.ledger.reserve_batch("peer", [(0, 17900)])[0]
        gateway.ledger.settle(ticket, 17900)
        return result

    manager.prepare = race
    with pytest.raises(AgentFailure) as exc:
        await gateway.invoke(messages, registry.schemas(), "1:r")
    assert exc.value.error.code == "BUDGET_EXCEEDED" and not gateway.transport.requests
    assert gateway.ledger.snapshot().total_tokens == 17900 and not gateway.ledger.pending


async def test_budget_compaction_archives_exact_protocol_and_protected_authority(settings):
    manager, gateway, registry, messages, _ = prepared_case(settings)
    before = messages_to_dict(messages)
    authority = manager.authority.model_dump_json()
    refs = {r.artifact_id: registry.store.get(r) for r in registry.refs}
    await gateway.invoke(messages, registry.schemas(), "1:r")
    assert manager.authority.model_dump_json() == authority
    assert [m.content for m in gateway.transport.requests[0][: len(manager.prefix)]] == [
        m.content for m in manager.prefix
    ]
    assert json.loads(manager.read_archive(registry.context_refs[-1])) == before
    assert refs == {r.artifact_id: registry.store.get(r) for r in registry.refs}


async def test_sdk_chat_input_excludes_host_metadata_but_estimator_remains_conservative(
    monkeypatch,
):
    requests = []

    async def reply(request):
        raw = json.loads(request.content)
        requests.append(raw)
        return httpx.Response(
            200,
            json={
                "id": "mock-only",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "total_tokens": 30,
                    "prompt_cache_hit_tokens": 6,
                    "prompt_cache_miss_tokens": 14,
                },
            },
        )

    ai = AIMessage(
        content="",
        id="host-id-not-wire",
        response_metadata={"private_host_metric": "x" * 1000},
        usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        tool_calls=[{"id": "pair", "name": "read_context", "args": {"artifact_id": "a" * 64}}],
    )
    messages = [
        HumanMessage(content="public synthetic goal"),
        ai,
        ToolMessage(content="public result", tool_call_id="pair", name="read_context"),
    ]
    cfg = Settings(
        _env_file=None,
        llm_mode="live",
        model_provider="deepseek",
        model="deepseek-flash",
        api_key="mock-only",
        base_url="https://unit.invalid",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as http:
        monkeypatch.setattr(provider, "ChatOpenAI", partial(ChatOpenAI, http_async_client=http))
        response = await live_transport(cfg).respond(messages, [])
    wire = requests[0]["messages"]
    assert wire[-1]["tool_call_id"] == wire[-2]["tool_calls"][0]["id"] == "pair"
    assert all(not {"response_metadata", "usage_metadata", "id"} & m.keys() for m in wire)
    assert "private_host_metric" not in json.dumps(wire)
    _, measured = measure_context(messages, [], 1200)
    assert measured.estimated_input_tokens > len(json.dumps(wire, ensure_ascii=False).encode())
    assert response.usage_metadata["total_tokens"] == 30
