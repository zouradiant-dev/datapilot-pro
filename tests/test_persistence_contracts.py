"""Local contract tests; no PostgreSQL or model provider claims."""

import copy
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from datapilot.contracts import AgentFailure
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.contracts import BudgetLimits
from datapilot.orchestration.model import Gateway
from datapilot.orchestration.runtime import Cancellation
from datapilot.persistence.session import serializer


def test_budget_roundtrip_keeps_parent_child_and_pending():
    ledger = BudgetLedger(BudgetLimits(calls=4, tokens=5000))
    ledger.fork("1:sql", BudgetLimits(calls=3, tokens=4000))
    ticket = ledger.reserve("1:sql", "bounded", 200)
    other = BudgetLedger(BudgetLimits())
    other.load_state(ledger.dump_state())
    other.settle(ticket, 15)
    ledger.settle(ticket, 15)
    assert other.dump_state() == ledger.dump_state()


@pytest.mark.parametrize("kind", ["ancestry", "limit", "pending", "usage"])
def test_invalid_budget_restore_is_rejected_without_replacing_live_state(kind):
    ledger = BudgetLedger(BudgetLimits(calls=4, tokens=5000))
    ledger.fork("1:sql", BudgetLimits(calls=3, tokens=4000))
    ticket = ledger.reserve("1:sql", "bounded", 200)
    before = ledger.dump_state()
    broken = copy.deepcopy(before)
    if kind == "ancestry":
        broken["accounts"]["1:sql"]["parent"] = "1:sql"
    elif kind == "limit":
        broken["accounts"]["1:sql"]["limits"]["calls"] = 5
    elif kind == "pending":
        broken["pending"][ticket][0] = ["1:sql"]
    else:
        broken["accounts"]["root"]["usage"]["calls"] = 0
    with pytest.raises(AgentFailure):
        ledger.load_state(broken)
    assert ledger.dump_state() == before


def test_checkpoint_serializer_rejects_executable_or_opaque_handles():
    with pytest.raises((TypeError, ValueError)):
        serializer().dumps_typed({"handle": object()})
    assert not serializer().pickle_fallback


async def test_durable_cached_response_skips_time_dependent_context_and_provider():
    response = AIMessage(
        content="complete",
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        },
    )

    class Journal:
        def model_identity(self, *args):
            return "canonical", "digest"

        def cached_model(self, *args):
            return response

    class NoCalls:
        async def prepare(self, *args):
            pytest.fail("Replaying canonical input must not rerun compression")

        async def respond(self, *args):
            pytest.fail("A committed provider call must not be sent again")

    settings = SimpleNamespace(
        max_input_chars=1000,
        max_output_tokens=100,
        model_timeout_seconds=1,
        max_context_tokens=1000,
    )
    gateway = Gateway(NoCalls(), settings, BudgetLedger(BudgetLimits()), Cancellation())
    gateway.durability = Journal()
    gateway.contexts["1:sql"] = NoCalls()
    assert (
        await gateway.invoke([HumanMessage(content="same canonical goal")], [], "1:sql") == response
    )
    assert gateway.ledger.snapshot().calls == 0
