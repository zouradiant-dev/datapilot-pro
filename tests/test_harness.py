import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from datapilot.contracts import AgentFailure, QueryResult, RouteDecision, SQLAgentResult, SQLTask
from datapilot.harness.budget import RunBudget
from datapilot.harness.verification import verify_completion
from datapilot.llm.client import JSONModelClient


class StubChat:
    def __init__(self, content):
        self.content = content

    def invoke(self, messages):
        return AIMessage(
            content=self.content,
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


def test_json_contract_and_budget(settings):
    budget = RunBudget(1, 18000)
    client = JSONModelClient(StubChat('{"route":"sql"}'), settings, budget)
    assert client.generate(RouteDecision, system="route", user="count").route == "sql"
    assert budget.calls == 1 and budget.reported_tokens == 15
    with pytest.raises(AgentFailure, match="budget"):
        client.generate(RouteDecision, system="route", user="count")


@pytest.mark.parametrize(
    "content", ['{"route":"invented"}', '{"route":"sql","extra":1}', "```json\n{}\n```"]
)
def test_invalid_model_outputs(settings, content):
    client = JSONModelClient(StubChat(content), settings, RunBudget(3, 18000))
    with pytest.raises(AgentFailure) as error:
        client.generate(RouteDecision, system="route", user="count")
    assert error.value.error.code == "MODEL_OUTPUT_INVALID"


def test_context_and_unknown_usage(settings):
    client = JSONModelClient(StubChat("{}"), settings, RunBudget(3, 18000))
    with pytest.raises(AgentFailure) as error:
        client.generate(RouteDecision, system="x" * 17000, user="count")
    assert error.value.error.code == "CONTEXT_LIMIT"
    budget = RunBudget(3, 3000)
    reservation = budget.reserve("hello", 1200)
    budget.settle(reservation, None)
    assert not budget.usage_complete and budget.total_tokens == reservation


def test_verifier_and_result_invariants():
    with pytest.raises(ValidationError):
        QueryResult(columns=["n"], rows=[[1, 2]], row_count=1, truncated=False, elapsed_ms=0.0)
    with pytest.raises(ValidationError):
        SQLAgentResult(task_id="a", status="succeeded", attempts=1)
    data = QueryResult(columns=["n"], rows=[[1]], row_count=1, truncated=False, elapsed_ms=0.0)
    result = SQLAgentResult(
        task_id="a", status="succeeded", sql="SELECT 1", result=data, attempts=1
    )
    with pytest.raises(AgentFailure, match="task_id"):
        verify_completion(SQLTask(task_id="b", question="count"), result, 100)


def test_model_failure_is_sanitized_and_still_charged(settings):
    class FailingProvider:
        def invoke(self, messages):
            raise RuntimeError("private-provider-detail")

    budget = RunBudget(3, 18000)
    client = JSONModelClient(FailingProvider(), settings, budget)
    with pytest.raises(AgentFailure) as error:
        client.generate(RouteDecision, system="route", user="count")
    assert error.value.error.code == "MODEL_ERROR"
    assert "private-provider-detail" not in error.value.error.message
    assert budget.calls == 1 and budget.total_tokens > 0 and not budget.usage_complete
