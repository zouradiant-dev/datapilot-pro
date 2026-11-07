"""Public concrete views; no private cases, Runtime, Provider or database."""

from dataclasses import asdict

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from test_context_engineering import make_context

from datapilot.contracts import AgentFailure
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.context import measure_context
from datapilot.orchestration.contracts import BudgetLimits
from evaluation.p7_v3_current.budget_admission import check_model_view


def setup_view(settings, tokens=18000, body=11000):
    _, manager, _, registry, prefix = make_context(settings, max_chars=16000, max_tokens=18000)
    limits = BudgetLimits(calls=8, tokens=tokens)
    ledger = BudgetLedger(limits)
    ledger.fork("documents", BudgetLimits(calls=4, tokens=tokens))
    ledger.fork("peer", limits)
    messages = [*prefix, HumanMessage(content="Public independent view. " + "x" * body)]
    return manager, ledger, messages, registry.schemas()


def test_parent_spending_is_visible_before_followup(settings):
    manager, ledger, messages, tools = setup_view(settings)
    _, usage = measure_context(messages, tools, manager.limits.output_tokens)
    required = usage.estimated_input_tokens + usage.output_reserved_tokens
    amount = 18000 - required + 1
    ticket = ledger.reserve_batch("peer", [(0, amount)])[0]
    ledger.settle(ticket, amount)
    before = ledger.dump_state()
    result = check_model_view(manager, ledger, "documents", messages, tools)
    assert result.context_fits and not result.budget_fits and not result.admitted
    assert result.available_tokens == required - 1
    assert ledger.dump_state() == before


def test_larger_cumulative_budget_keeps_original_window(settings):
    manager, ledger, messages, tools = setup_view(settings, tokens=36000)
    ticket = ledger.reserve_batch("peer", [(0, 8000)])[0]
    ledger.settle(ticket, 8000)
    before = ledger.dump_state()
    result = check_model_view(manager, ledger, "documents", messages, tools)
    assert result.admitted and result.available_tokens == 28000
    assert manager.limits.max_tokens == 18000 and manager.limits.max_chars == 16000
    assert ledger.dump_state() == before
    assert "Public independent view" not in str(asdict(result))


def test_pending_reservations_already_reduce_headroom(settings):
    manager, ledger, messages, tools = setup_view(settings)
    ledger.reserve_batch("peer", [(0, 15000)])
    before = ledger.dump_state()
    result = check_model_view(manager, ledger, "documents", messages, tools)
    assert not result.admitted and result.available_tokens == 3000
    assert ledger.dump_state() == before


def test_ample_budget_does_not_override_input_window(settings):
    manager, ledger, messages, tools = setup_view(settings, tokens=36000, body=20000)
    result = check_model_view(manager, ledger, "documents", messages, tools)
    assert result.budget_fits and not result.context_fits and not result.admitted


def test_admission_is_not_a_reservation_or_dispatch_permission(settings):
    manager, ledger, messages, tools = setup_view(settings)
    assert check_model_view(manager, ledger, "documents", messages, tools).admitted
    ledger.reserve_batch("peer", [(0, 15000)])
    with pytest.raises(AgentFailure) as caught:
        ledger.reserve("documents", measure_context(messages, tools, 1200)[0], 1200)
    assert caught.value.error.code == "BUDGET_EXCEEDED"


def test_broken_tool_pairing_is_not_admitted(settings):
    manager, ledger, messages, tools = setup_view(settings)
    messages.append(ToolMessage(content="orphan", tool_call_id="unknown", name="search_documents"))
    with pytest.raises(AgentFailure) as caught:
        check_model_view(manager, ledger, "documents", messages, tools)
    assert caught.value.error.code == "CONTEXT_LIMIT"
