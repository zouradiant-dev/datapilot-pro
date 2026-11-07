"""Report planning proposals preserve approved work despite unavailable conclusions."""

import copy
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import ValidationError
from test_cross_dataset_document_facts import combined as combined
from test_cross_dataset_document_facts import reconfirm
from test_cross_source_report import bridge_case as bridge_case
from test_report_causal_scope import document_case
from test_semantics import semantic_case as semantic_case

from datapilot.contracts import AgentFailure
from datapilot.orchestration.contracts import Plan, ReportPlan, TaskSpec
from datapilot.orchestration.model import FakeTransport
from datapilot.persistence.session import serializer
from datapilot.reporting.contracts import UnboundMetricGoal


def proposal(service):
    menu = service.plan_menu()
    return {
        "tasks": [
            *menu,
            {
                "task_id": "report",
                "worker": "report",
                "instruction": "Summarize verified evidence and explicit gaps",
                "dependencies": [goal["task_id"] for goal in menu],
            },
        ],
        "unsupported": False,
    }


class ReplyGateway:
    def __init__(self, reply):
        self.reply, self.requests = reply, []

    async def invoke(self, messages, tools, account):
        self.requests.append((messages, tools, account))
        return self.reply


@pytest.mark.parametrize(
    ("unsupported", "tasks", "generic_valid", "report_valid"),
    [
        (False, True, True, True),
        (True, False, True, False),
        (True, True, False, False),
        (False, False, False, False),
    ],
)
def test_report_supported_branch_is_distinct_from_generic_unsupported(
    unsupported, tasks, generic_valid, report_valid
):
    value = {
        "unsupported": unsupported,
        "tasks": [{"task_id": "sql", "worker": "sql", "instruction": "Query"}] if tasks else [],
    }
    for contract, valid in [(Plan, generic_valid), (ReportPlan, report_valid)]:
        if valid:
            result = contract.model_validate_json(json.dumps(value))
            assert result.unsupported is unsupported
        else:
            with pytest.raises(ValidationError):
                contract.model_validate_json(json.dumps(value))


@pytest.mark.parametrize("unsupported", [0, 1, "false", "true", None])
def test_report_does_not_coerce_a_false_literal(unsupported):
    with pytest.raises(ValidationError):
        ReportPlan.model_validate_json(
            json.dumps(
                {
                    "tasks": [{"task_id": "sql", "worker": "sql", "instruction": "Query"}],
                    "unsupported": unsupported,
                }
            )
        )


@pytest.mark.parametrize("kind", ["sql", "rag", "combined", "partial", "unavailable", "unbound"])
async def test_report_plan_keeps_approved_goals_for_supported_report_outcomes(
    kind, settings, bridge_case, combined
):
    service = combined[0]
    if kind in {"sql", "unavailable"}:
        service = bridge_case[0]
        if kind == "unavailable":
            goal = service.scope.metrics[0].goal_id
            service.contexts[goal] = None
            service.problems[goal] = "METRIC_NOT_AVAILABLE"
    elif kind == "rag":
        service = document_case(settings, "Summarize the authorized public document")[0]
    elif kind == "partial":
        service.scope.causal_requested = True
        reconfirm(combined)
    elif kind == "unbound":
        service.scope.unbound_metric_goals = [
            UnboundMetricGoal(
                goal_id="pending", description="Actual missing metric", reason="definition_missing"
            )
        ]
        service.scope.document_goal.evidence_only = True
        reconfirm(combined)
    expected = proposal(service)
    gateway = ReplyGateway(AIMessage(content=json.dumps(expected)))
    result = await service.plan(gateway)
    assert isinstance(result, ReportPlan) and result.unsupported is False
    assert {task.task_id for task in result.tasks} == {
        *[goal["task_id"] for goal in service.plan_menu()],
        "report",
    }
    assert "pending" not in {task.task_id for task in result.tasks}
    assert len(gateway.requests) == 1
    messages, tools, account = gateway.requests[0]
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage) and messages[1].content == service.scope.question
    assert tools == [] and account == "root"
    schema = json.JSONDecoder().raw_decode(messages[0].content.split("matching ", 1)[1])[0]
    assert schema["properties"]["unsupported"]["const"] is False
    assert schema["properties"]["unsupported"]["type"] == "boolean"
    assert schema["properties"]["tasks"]["minItems"] == 1
    assert "Partial evidence, unavailable metrics" in messages[0].content
    assert "unverified causality are report outcomes" in messages[0].content


@pytest.mark.parametrize("unsupported", [True, False])
async def test_report_rejects_unsupported_or_empty_response_without_reinterpreting_it(
    bridge_case, unsupported
):
    service = bridge_case[0]
    value = proposal(service)
    value["unsupported"] = unsupported
    if not unsupported:
        value["tasks"] = []
    original = copy.deepcopy(value)
    gateway = ReplyGateway(AIMessage(content=json.dumps(value)))
    with pytest.raises(ValidationError):
        await service.plan(gateway)
    assert value == original and len(gateway.requests) == 1


@pytest.mark.parametrize(
    "mutation", ["added", "omitted", "worker", "dependency", "duplicate", "cycle", "authority"]
)
async def test_report_response_cannot_change_host_coverage_capability_or_dag(
    bridge_case, combined, mutation
):
    service = combined[0] if mutation == "dependency" else bridge_case[0]
    value = proposal(service)
    goal = value["tasks"][0]
    if mutation == "added":
        value["tasks"].insert(1, {"task_id": "extra", "worker": "sql", "instruction": "Query"})
    elif mutation == "omitted":
        value["tasks"] = [goal]
    elif mutation == "worker":
        goal["worker"] = "rag"
    elif mutation == "dependency":
        goal["dependencies"] = [value["tasks"][1]["task_id"]]
    elif mutation == "duplicate":
        value["tasks"].insert(1, copy.deepcopy(goal))
    elif mutation == "cycle":
        goal["dependencies"] = ["report"]
    else:
        goal["dataset_id"] = "00000000-0000-4000-8000-000000000999"
    gateway = ReplyGateway(AIMessage(content=json.dumps(value)))
    with pytest.raises((AgentFailure, ValidationError)):
        await service.plan(gateway)
    assert len(gateway.requests) == 1


@pytest.mark.parametrize("invalid", [False, True])
async def test_report_planner_cannot_call_tools(bridge_case, invalid):
    service = bridge_case[0]
    value = proposal(service)
    if invalid:
        reply = AIMessage(
            content=json.dumps(value),
            invalid_tool_calls=[{"id": "invalid", "name": "query", "args": "{", "error": "bad"}],
        )
    else:
        reply = AIMessage(
            content=json.dumps(value), tool_calls=[{"id": "tool", "name": "query", "args": {}}]
        )
    with pytest.raises(AgentFailure) as error:
        await service.plan(ReplyGateway(reply))
    assert error.value.error.code == "PLAN_INVALID"


async def test_existing_public_fake_protocol_remains_compatible(combined):
    service = combined[0]
    transport = FakeTransport(None)

    class FakeGateway:
        async def invoke(self, messages, tools, account):
            assert tools == [] and account == "root"
            return await transport.respond(messages, tools)

    result = await service.plan(FakeGateway())
    assert isinstance(result, ReportPlan)
    assert [task.worker for task in result.tasks] == ["sql", "rag", "report"]
    assert result.tasks[-1].dependencies == [goal["task_id"] for goal in service.plan_menu()]
    restored = serializer().loads_typed(serializer().dumps_typed(result))
    assert type(restored) is ReportPlan and restored == result


def test_generic_plan_serialization_stays_compatible():
    plan = Plan(tasks=[TaskSpec(task_id="sql", worker="sql", instruction="Query")])
    assert plan.model_dump() == {
        "tasks": [
            {
                "task_id": "sql",
                "worker": "sql",
                "instruction": "Query",
                "dependencies": [],
                "operation": None,
                "columns": [],
            }
        ],
        "unsupported": False,
    }
    assert Plan(unsupported=True).model_dump() == {"tasks": [], "unsupported": True}
