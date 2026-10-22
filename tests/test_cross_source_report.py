"""Local contracts/adversarial projections; no PostgreSQL or real model claims."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_semantics import execution_case
from test_semantics import semantic_case as semantic_case

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetBinding, DatasetScope
from datapilot.harness.metric_verification import make_evidence, verify_execution
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact, Plan, TaskEnvelope, TaskSpec
from datapilot.orchestration.runtime import ArtifactStore
from datapilot.persistence.session import serializer
from datapilot.reporting.contracts import MetricBridge, ReportScope
from datapilot.reporting.service import ReportService


@pytest.fixture
def bridge_case(settings, semantic_case):
    context, request = semantic_case()
    execution = execution_case(context, request)
    evidence = make_evidence(execution)
    verification = verify_execution(execution, evidence, evidence)
    assert verification.verdict == "verified"
    scope = ReportScope(
        question="查看已支付账单收入",
        datasets=DatasetScope(
            bindings=[
                DatasetBinding(dataset_id=request.dataset_id, version=request.dataset_version)
            ]
        ),
        metrics=[request],
    )
    service = ReportService(
        settings,
        scope,
        {},
        {request.goal_id: context},
        {request.dataset_id: {"source_sha256": context.source_sha256, "version": 1}},
        {},
    )
    service.proofs[evidence.evidence_id] = (evidence, verification)  # Explicit metadata double.
    bridge = MetricBridge(
        request=request,
        source_sha256=context.source_sha256,
        context=context,
        evidence_id=evidence.evidence_id,
        evidence_sha256=digest(evidence),
        query_sha256=evidence.query_sha256,
        result_sha256=evidence.result_sha256,
        verification=verification,
        verification_sha256=digest(verification),
        verdict="verified",
        value=evidence.value,
        verified_at=datetime.now(UTC),
    )
    store = ArtifactStore("unit-report")
    ref = store.put(
        Artifact(
            run_id="unit-report",
            task_id=request.goal_id,
            plan_version=1,
            kind="metric",
            source="unit-P3-double",
            metric=bridge,
        )
    )
    return service, bridge, [(ref, store.get(ref))]


def test_bridge_report_chart_and_cache_prerequisites_are_explicit(bridge_case):
    service, bridge, inputs = bridge_case
    report = service.build(inputs, None)
    assert report.business_completion.status == "completed"
    assert report.claims[0].metric == bridge
    assert report.charts[0].points[0].metric == bridge
    assert report.charts[0].authorization_sha256 == report.authorization_sha256
    assert bridge.context.definition.paid_values == ["paid"]
    assert bridge.request.window.end_exclusive.isoformat() == "2025-11-01"
    assert bridge.verification.verification_id in report.markdown
    assert bridge.evidence_id in report.markdown and "300" in report.markdown
    service.verify_report(report, inputs, None)
    restored = serializer().loads_typed(serializer().dumps_typed(report))
    assert restored == report


@pytest.mark.parametrize(
    "mutation", ["unit", "value", "version", "source", "evidence", "hash", "verdict"]
)
def test_invalid_metric_bridge_cannot_publish_number(bridge_case, mutation):
    service, bridge, _ = bridge_case
    bad = bridge.model_copy(deep=True)
    if mutation == "unit":
        bad.value.unit = "USD"
    elif mutation == "value":
        bad.value.value = "30000"
    elif mutation == "version":
        bad.request.metric_version += 1
    elif mutation == "source":
        bad.source_sha256 = "0" * 64
    elif mutation == "evidence":
        bad.evidence_id = str(uuid4())
    elif mutation == "hash":
        bad.evidence_sha256 = "0" * 64
    else:
        bad.verdict = "unavailable"
    with pytest.raises((AgentFailure, ValidationError)):
        service.verify_metric(bad)


@pytest.mark.parametrize(
    "mutation", ["markdown", "chart_value", "chart_unit", "scope", "claim_ref"]
)
def test_report_is_independently_rebuilt_not_self_verified(bridge_case, mutation):
    service, _, inputs = bridge_case
    report = service.build(inputs, None)
    if mutation == "markdown":
        report.markdown += "收入一定是 99999，已验证。"
    elif mutation == "chart_value":
        report.charts[0].points[0].metric.value.value = "99999"
    elif mutation == "chart_unit":
        report.charts[0].unit = "USD"
    elif mutation == "scope":
        report.authorization_sha256 = "0" * 64
    else:
        report.claims[0].metric.verification.verification_id = str(uuid4())
    with pytest.raises((AgentFailure, ValidationError)):
        service.verify_report(report, inputs, None)


def test_causality_is_unconfirmed_while_verified_descriptive_metric_remains_visible(bridge_case):
    service, _, inputs = bridge_case
    service.scope.question = "解释收入变化的原因"
    report = service.build(inputs, None)
    assert report.business_completion.status == "partial"
    assert report.execution_status == "succeeded"
    assert report.business_completion.unconfirmed_claims == ["causal_conclusion_not_verified"]
    assert report.claims[0].metric.verification.verdict == "verified"


def test_raw_query_artifact_does_not_become_a_verified_metric(bridge_case):
    service, _, _ = bridge_case
    report = service.build([], None)
    assert report.business_completion.status == "unavailable" and not report.charts
    assert report.claims[0].metric is None


def test_planner_cannot_add_drop_or_reassign_confirmed_metric_goals(bridge_case):
    service, bridge, _ = bridge_case
    g = bridge.request.goal_id
    valid = Plan(
        tasks=[
            TaskSpec(task_id=g, worker="sql", instruction="已确认指标"),
            TaskSpec(task_id="report", worker="report", instruction="报告", dependencies=[g]),
        ]
    )
    assert service.validate_plan(valid) == valid
    for plan in [
        Plan(unsupported=True),
        valid.model_copy(update={"tasks": valid.tasks[1:]}),
        valid.model_copy(
            update={"tasks": [valid.tasks[0].model_copy(update={"worker": "rag"}), valid.tasks[1]]}
        ),
    ]:
        with pytest.raises(AgentFailure):
            service.validate_plan(plan)


def test_legacy_artifact_and_envelope_hashes_remain_compatible():
    old = {
        "run_id": "old",
        "task_id": "sql",
        "plan_version": 1,
        "kind": "schema",
        "source": "MCP",
        "sql": None,
        "query": None,
        "documents": None,
        "values": {"schema": "schema"},
        "parents": [],
    }
    artifact = Artifact.model_validate(old)
    assert digest(artifact) == digest(old)
    assert "metric" not in artifact.model_dump() and "report" not in artifact.model_dump()
    envelope = TaskEnvelope(
        run_id="old",
        parent_id="old",
        plan_version=1,
        task=TaskSpec(task_id="sql", worker="sql", instruction="客户数"),
        allowed_tools=[],
        budget={"calls": 2, "tokens": 1000},
    )
    assert "dependency_statuses" not in envelope.model_dump()


async def test_local_recovery_only_retries_missing_ready_goal_not_all_sources(
    bridge_case, monkeypatch
):
    """Known rollback is simulated; no external side effect or real LLM is claimed."""
    import json

    from langchain_core.messages import AIMessage
    from test_orchestration import DatabaseMock, initial

    from datapilot.orchestration.coordinator import Coordinator
    from datapilot.semantics.contracts import MissingRequirement

    service, bridge, _ = bridge_case
    original = bridge.request.goal_id
    unavailable = bridge.request.model_copy(
        update={"goal_id": "missing_definition", "metric_version": 999}
    )
    service.scope.metrics.append(unavailable)
    service.requests[unavailable.goal_id] = unavailable
    service.contexts[unavailable.goal_id] = None
    service.problems[unavailable.goal_id] = "METRIC_NOT_CONFIRMED"
    counts = {original: 0, unavailable.goal_id: 0}

    async def compute(goal):
        counts[goal] += 1
        if goal == original:
            if counts[goal] == 1:
                raise AgentFailure(
                    "QUERY_CANCELLED", "Mock confirmed transaction rollback", retryable=True
                )
            return bridge
        return MetricBridge(
            request=unavailable,
            source_sha256=bridge.source_sha256,
            verdict="unavailable",
            missing=[MissingRequirement(code="metric_not_confirmed", message="需要确认")],
            verified_at=datetime.now(UTC),
        )

    async def refresh(artifacts):
        for a in artifacts:
            if a.metric:
                service.verify_metric(a.metric)

    class Decisions:
        calls = 0

        async def respond(self, messages, tools):
            self.calls += 1
            goals = json.loads(messages[0].content.split("HOST_APPROVED_GOALS: ", 1)[1])
            return AIMessage(
                content=Plan(
                    tasks=[
                        *[TaskSpec(**g) for g in goals],
                        TaskSpec(
                            task_id="report",
                            worker="report",
                            instruction="输出报告",
                            dependencies=[g["task_id"] for g in goals],
                        ),
                    ]
                ).model_dump_json()
            )

    monkeypatch.setattr(service, "compute", compute)
    monkeypatch.setattr(service, "refresh", refresh)
    decisions = Decisions()
    engine = Coordinator(
        service.settings, decisions, database=DatabaseMock(), reporting=service, run_id="unit-run"
    )
    state = await engine.graph.ainvoke(initial(service.scope.question))
    assert state["replans"] == 1, [
        (k, r.status, r.error.code if r.error else None, r.error.retryable if r.error else None)
        for k, r in state["results"].items()
    ]
    assert counts == {original: 2, unavailable.goal_id: 1}
    assert decisions.calls == 1  # No full model replan.
    assert state["business_completion"].status == "partial"
    assert state["cross_source_report"].claims[0].metric == bridge
    assert state["results"]["2:missing_definition"].reused_from == "1:missing_definition"


def test_failed_orchestration_verdict_is_not_hidden_by_successful_tool(bridge_case):
    from test_orchestration import DatabaseMock

    from datapilot.orchestration.contracts import ExecutionError, TaskResult, VerificationResult
    from datapilot.orchestration.coordinator import Coordinator

    service, bridge, inputs = bridge_case
    goal = bridge.request.goal_id
    engine = Coordinator(
        service.settings, None, database=DatabaseMock(), reporting=service, run_id="unit-report"
    )
    task = TaskSpec(task_id="report", worker="report", instruction="报告", dependencies=[goal])
    k = "1:" + goal
    state = {
        "run_id": "unit-report",
        "plan_version": 1,
        "results": {
            k: TaskResult(
                run_id="unit-report",
                task_id=goal,
                plan_version=1,
                worker="sql",
                status="succeeded",
                evidence_refs=[inputs[0][0]],
            )
        },
        "verifications": {
            k: VerificationResult(
                task_id=goal,
                plan_version=1,
                status="failed",
                checks=["identity", "capability", "evidence", "shape", "dependencies"],
                error=ExecutionError(
                    code="EVIDENCE_INVALID", message="wrong task", category="verification"
                ),
            )
        },
    }
    envelope = engine.envelope(state, task)
    assert envelope.dependency_statuses == {goal: "failed"}
    assert not envelope.input_refs
    report = service.build([], None, source_statuses=envelope.dependency_statuses)
    assert report.business_completion.status == "blocked"
    assert report.execution_status == "failed" and not report.charts
