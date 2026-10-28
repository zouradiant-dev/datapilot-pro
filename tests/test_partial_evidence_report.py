"""Public synthetic partial facts; explicit host policy, no model or Holdout output."""

import pytest
from test_cross_source_report import bridge_case as bridge_case
from test_document_fact_coverage import fact, synthetic
from test_semantics import semantic_case as semantic_case

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.reporting.contracts import ReportScope


@pytest.mark.parametrize("policy", ["legacy", "partial-facts-v1"])
async def test_worker_to_report_preserves_receipt_and_verifies_partial_refs(settings, policy):
    import json

    from test_cross_source_postgres import ReportDecisions

    from datapilot.orchestration.coordinator import Coordinator
    from datapilot.orchestration.rag_completion import PROTOCOL

    service, pairs, retrieval = partial_case(settings)
    service.scope.partial_evidence_policy = policy
    retrieval.completion_protocol = PROTOCOL
    retrieval.max_search_attempts = 2

    async def search(*_):
        return pairs[0][1].documents.model_copy(deep=True)

    retrieval.search = search

    class Insufficient(ReportDecisions):
        async def respond(self, messages, tools):
            reply = await super().respond(messages, tools)
            for call in reply.tool_calls:
                if call["name"] == "submit_rag_result":
                    call["args"]["outcome"] = "insufficient"
            return reply

    engine = Coordinator(
        settings,
        Insufficient(service.scope.question),
        retrieval=retrieval,
        reporting=service,
        run_id="partial-contract-run",
    )
    result = await engine.graph.ainvoke(
        {
            "run_id": engine.run_id,
            "question": service.scope.question,
            "status": "pending",
            "results": {},
            "verifications": {},
            "steps": 0,
            "replans": 0,
            "error": None,
        },
        config={"recursion_limit": 80},
    )
    worker = result["results"]["1:documents"]
    assert worker.status == "unavailable"
    assert worker.rag_completion.submission.outcome == "insufficient"
    assert worker.rag_completion.verdict == "insufficient"
    assert result["verifications"]["1:documents"].status == "unavailable"
    assert result["business_completion"].status == (
        "partial" if policy == "partial-facts-v1" else "unavailable"
    )
    if policy == "partial-facts-v1":
        report_task = next(t for t in result["plan"].tasks if t.task_id == "report")
        assert engine.envelope(result, report_task).input_refs == worker.evidence_refs
        # A forged checkpoint verdict cannot substitute for the original accepted receipt.
        engine.rag_receipts.clear()
        assert not engine.envelope(result, report_task).input_refs
        report_result = result["results"]["1:report"]
        assert engine.verify(result, report_task, report_result).status == "failed"
    assert not any(
        json.loads(m.content).get("sql")
        for m in engine.transcripts["1:documents"]
        if m.type == "tool"
    )


def partial_case(settings):
    service, pairs, retrieval = synthetic(settings, purpose="facts")
    service.scope = service.scope.model_copy(update={"partial_evidence_policy": "partial-facts-v1"})
    service.scope.document_goal.required_facts = [
        fact(pairs, "review", "按月复核角色权限"),
        fact(pairs, "retention"),
    ]
    return service, pairs, retrieval


def test_insufficient_keeps_literal_fact_without_completing_goal(settings):
    service, pairs, retrieval = partial_case(settings)
    report = service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    assert report.business_completion.status == "partial"
    assert report.business_completion.verified_goals == []
    assert report.claims[0].fact_coverage["review"].excerpt == "按月复核角色权限"
    assert report.claims[0].fact_coverage["retention"] is None
    assert "rag_task_insufficient" in report.business_completion.missing_evidence["documents"]
    assert not report.charts and all(c.metric is None for c in report.claims)
    service.verify_report(report, pairs, retrieval, source_statuses={"documents": "unavailable"})


def test_source_count_shortfall_does_not_hide_proved_fact(settings):
    service, pairs, retrieval = partial_case(settings)
    service.scope.question = service.scope.document_goal.question = (
        "至少两份文档说明权限复核和日志期限。"
    )
    report = service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    assert report.business_completion.status == "partial"
    assert report.claims[0].fact_coverage["review"]
    assert (
        "matching_document_or_metric_evidence_missing"
        in (report.business_completion.missing_evidence["documents"])
    )


def test_all_facts_with_insufficient_receipt_still_cannot_complete(settings):
    service, pairs, retrieval = partial_case(settings)
    service.scope.document_goal.required_facts = [fact(pairs, "review", "按月复核角色权限")]
    report = service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    assert report.business_completion.status == "partial"
    assert not report.business_completion.verified_goals


@pytest.mark.parametrize("status", ["failed", "blocked", "cancelled", "missing"])
def test_invalid_or_missing_dependency_never_supplies_partial_facts(settings, status):
    service, pairs, retrieval = partial_case(settings)
    statuses = {} if status == "missing" else {"documents": status}
    report = service.build(pairs, retrieval, source_statuses=statuses)
    assert not any(c.kind == "context" for c in report.claims)
    assert report.business_completion.status != "completed"


def test_background_without_host_fact_proof_stays_unavailable(settings):
    service, pairs, retrieval = partial_case(settings)
    service.scope.document_goal.required_facts = [fact(pairs)]
    report = service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    assert report.business_completion.status == "unavailable"
    assert not any(c.kind == "context" for c in report.claims)


def test_completed_source_still_requires_all_facts_under_new_policy(settings):
    service, pairs, retrieval = partial_case(settings)
    service.scope.document_goal.required_facts = [fact(pairs, "review", "按月复核角色权限")]
    report = service.build(pairs, retrieval, source_statuses={"documents": "succeeded"})
    assert report.business_completion.status == "completed"
    assert report.business_completion.verified_goals == ["documents"]


def test_unsupported_snapshot_cannot_publish_partial_fact(settings):
    service, pairs, retrieval = partial_case(settings)
    service.scope.question = service.scope.document_goal.question = "按最新快照说明权限复核规则。"
    report = service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    assert report.business_completion.status == "unavailable"
    assert report.business_completion.missing_evidence["documents"] == ["snapshot_not_attested"]
    assert not any(c.kind == "context" for c in report.claims)


@pytest.mark.parametrize("mutation", ["reference", "source", "irrelevant", "wrong_fact_pin"])
def test_invalid_partial_evidence_never_publishes_fact(settings, mutation):
    service, pairs, retrieval = partial_case(settings)
    if mutation == "reference":
        pairs[0][0].sha256 = "0" * 64
    elif mutation == "source":
        retrieval.validate_result = lambda _: (_ for _ in ()).throw(
            AgentFailure("DOCUMENT_NOT_AUTHORIZED", "Revoked or changed source")
        )
    elif mutation == "irrelevant":
        retrieval.qualifying_documents = lambda *_: []
    else:
        service.scope.document_goal.required_facts[0].citation.index_version = "0" * 64
    if mutation in {"reference", "source"}:
        with pytest.raises(AgentFailure):
            service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    else:
        assert (
            service.build(
                pairs, retrieval, source_statuses={"documents": "unavailable"}
            ).business_completion.status
            == "unavailable"
        )


def test_causal_request_and_missing_fact_survive_partial_display(settings):
    service, pairs, retrieval = partial_case(settings)
    service.scope.causal_requested = True
    report = service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    assert report.business_completion.status == "partial"
    assert report.business_completion.unconfirmed_claims == ["causal_conclusion_not_verified"]
    assert (
        "document_fact_unverified:retention"
        in (report.business_completion.missing_evidence["documents"])
    )


def test_metric_verdict_is_unchanged_by_partial_document_policy(settings, bridge_case):
    service, bridge, metric_inputs = bridge_case
    docs, pairs, retrieval = partial_case(settings)
    service.scope.document_goal = docs.scope.document_goal
    service.scope.partial_evidence_policy = "partial-facts-v1"
    service.scope.document_goal.metric_goals = [bridge.request.goal_id]
    # The related-topic guard is retained.
    report = service.build(
        metric_inputs + pairs, retrieval, source_statuses={"documents": "unavailable"}
    )
    assert report.claims[0].metric == bridge and bridge.verdict == "verified"
    assert report.business_completion.status == "partial"


def test_legacy_scope_hash_and_legacy_behavior_are_preserved(settings):
    service, pairs, retrieval = partial_case(settings)
    raw = service.scope.model_dump(mode="json")
    raw.pop("partial_evidence_policy", None)
    legacy = ReportScope.model_validate(raw)
    assert legacy.model_dump(mode="json") == raw and digest(legacy) == digest(raw)
    service.scope = legacy
    assert (
        service.build(
            pairs, retrieval, source_statuses={"documents": "unavailable"}
        ).business_completion.status
        == "unavailable"
    )


def test_old_report_cannot_be_reinterpreted_under_new_policy(settings):
    service, pairs, retrieval = partial_case(settings)
    service.scope = ReportScope.model_validate(
        {
            k: v
            for k, v in service.scope.model_dump(mode="json").items()
            if k != "partial_evidence_policy"
        }
    )
    legacy = service.build(pairs, retrieval, source_statuses={"documents": "unavailable"})
    service.scope = service.scope.model_copy(update={"partial_evidence_policy": "partial-facts-v1"})
    with pytest.raises(AgentFailure):
        service.verify_report(
            legacy, pairs, retrieval, source_statuses={"documents": "unavailable"}
        )
