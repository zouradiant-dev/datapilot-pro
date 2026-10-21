from datapilot.agents.sql import SQLAgent
from datapilot.contracts import AgentFailure, QueryResult, SQLTask
from datapilot.graph import build_graph
from datapilot.harness.budget import RunBudget
from datapilot.llm.fake import FakeModelClient


class MockDatabaseTools:
    """Explicit unit mock; these rows are never claimed as database verification."""

    def __init__(self):
        self.queries = []

    async def schema(self):
        return "saas.customers(customer_id INTEGER)"

    async def execute(self, sql):
        self.queries.append(sql)
        if "bad_field" in sql:
            raise AgentFailure(
                "SQL_EXECUTION_ERROR", 'column "bad_field" does not exist', retryable=True
            )
        if "DELETE" in sql:
            raise AgentFailure("SQL_UNSAFE", "Only SELECT is allowed")
        return QueryResult(columns=["n"], rows=[[5]], row_count=1, truncated=False, elapsed_ms=0.0)


async def test_worker_bounded_repair_and_isolated_context(settings):
    fake = FakeModelClient(
        settings,
        RunBudget(3, 18000),
        scripted_sql=["SELECT bad_field FROM customers", "SELECT COUNT(*) AS n FROM customers"],
    )
    tools = MockDatabaseTools()
    result = await SQLAgent(fake, tools).run(SQLTask(task_id="sql1", question="查询客户总数"))
    assert result.status == "succeeded" and result.attempts == 2
    assert "COMPILER ERROR" in fake.contexts[1][1]
    assert "Supervisor" not in fake.contexts[0][1]


async def test_worker_terminal_failure_and_no_retry_for_unsafe(settings):
    for sql, attempts, code in (
        ("SELECT bad_field FROM customers", 2, "SQL_EXECUTION_ERROR"),
        ("DELETE FROM customers", 1, "SQL_UNSAFE"),
    ):
        fake = FakeModelClient(settings, RunBudget(3, 18000), scripted_sql=[sql, sql])
        result = await SQLAgent(fake, MockDatabaseTools()).run(
            SQLTask(task_id="a", question="query")
        )
        assert result.status == "failed" and result.result is None
        assert result.attempts == attempts and result.error.code == code


async def test_actual_langgraph_routing_and_step_limit(settings):
    events = []
    fake = FakeModelClient(settings, RunBudget(3, 18000))
    graph = build_graph(settings, fake, MockDatabaseTools(), events)
    state = {
        "run_id": "test",
        "question": "查询客户总数",
        "status": "pending",
        "task": None,
        "result": None,
        "error": None,
        "steps": 0,
        "answer": "",
    }
    result = await graph.ainvoke(state)
    assert result["status"] == "succeeded" and "| 5 |" in result["answer"]
    assert [
        e["node"] for e in events if e["node"] in {"planner", "scheduler", "verifier", "finish"}
    ] == ["planner", "scheduler", "verifier", "finish"]
    limited = settings.model_copy(update={"max_steps": 1})
    result = await build_graph(limited, fake, MockDatabaseTools(), []).ainvoke(state)
    assert result["status"] == "failed" and result["error"].code == "STEP_LIMIT"
