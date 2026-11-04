"""Public signed partial-receipt controls, with no sealed task, database or provider I/O."""

import copy
import importlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from test_p7_current_citation_scoring import example as example
from test_p7_current_citation_scoring import recommit
from test_p7_scorer_versions import case as case

from datapilot.ingestion.common import digest
from datapilot.orchestration.rag_completion import goal_hash, retrieval_goal
from datapilot.reporting.contracts import DocumentFact, ReportScope, confirm_finite_scope
from evaluation.p7_v3_current.partial_evidence_scope import confirm_partial_literals


def rebind(data, *, policy="partial-facts-v1", attested=True):
    task, payload = data.task, data.payload
    scope = ReportScope(
        owner=task.owner,
        question=task.question,
        datasets=task.datasets,
        metrics=task.metrics,
        document_goal=task.document_goal,
        partial_evidence_policy=policy,
    )
    if attested:
        scope = confirm_finite_scope(
            scope, task.rag_scope, confirmation_ref="public-reviewed-partial-literal-contract"
        )
    data.scope = scope
    payload["manifest"]["cross_source_report"]["scope"] = scope.model_dump(mode="json")
    report = payload["snapshot"]["report"]
    report["authorization_scope"] = scope.model_dump(mode="json")
    report["authorization_sha256"] = digest(scope)
    goal = retrieval_goal(task.document_goal.question, SimpleNamespace(scope=task.rag_scope), scope)
    payload["manifest"]["rag_completion_goal"] = goal
    payload["snapshot"]["state"]["results"]["1:documents"]["rag_completion"]["goal_sha256"] = (
        goal_hash(goal)
    )
    recommit(data)


@pytest.fixture
def partial(example):
    data = example
    first = data.payload["snapshot"]["report"]["claims"][0]["documents"][0]
    quote = "required fact."
    data.task.document_goal.purpose = "facts"
    data.task.document_goal.required_facts = [
        DocumentFact.model_validate_json(
            json.dumps(
                {
                    "fact_id": "fact_1",
                    "description": "Known public fact",
                    "citation": first["citation"],
                    "quotation": quote,
                    "confirmation_ref": "public-reviewed-source-quote",
                }
            )
        ),
        DocumentFact(fact_id="fact_2", description="Unknown public requirement"),
    ]
    data.gold.business_completion = "partial"
    data.gold.missing_fact_ids = ["fact_2"]
    data.gold.retrieval["facts"][0].update(literal=quote, start=7)
    claim = data.payload["snapshot"]["report"]["claims"][0]
    claim["documents"] = [first]
    first["excerpt"] = quote
    claim["fact_coverage"] = {"fact_1": copy.deepcopy(first), "fact_2": None}
    report = data.payload["snapshot"]["report"]
    report["execution_status"] = "unavailable"
    report["business_completion"].update(
        status="partial",
        verified_goals=[],
        missing_evidence={
            "documents": ["document_fact_unverified:fact_2", "rag_task_insufficient"]
        },
    )
    result = data.payload["snapshot"]["state"]["results"]["1:documents"]
    result.update(
        status="unavailable",
        error={"code": "EVIDENCE_INSUFFICIENT", "message": "Partial source", "category": "tool"},
    )
    result["rag_completion"].update(verdict="insufficient", relevant_chunk_ids=[])
    result["rag_completion"]["submission"]["outcome"] = "insufficient"
    data.payload["snapshot"]["state"]["verifications"]["1:documents"].update(
        status="unavailable", error=result["error"]
    )
    rebind(data)
    # Match the report's known-fact reference to its final artifact identity.
    claim["fact_coverage"]["fact_1"]["artifact_id"] = first["artifact_id"]
    data.new_scorer = importlib.import_module("partial_evidence_scorer")
    return data


def evaluate(data, *, old=False):
    import p7_business_evaluator
    import p7_business_scoring

    def goal(question):
        assert question == data.task.document_goal.question
        return retrieval_goal(question, SimpleNamespace(scope=data.task.rag_scope), data.scope)

    fn = data.scorer.score if old else data.new_scorer.score
    with (
        patch.object(p7_business_scoring, "ReportScope", return_value=data.scope),
        patch.object(p7_business_evaluator, "retrieval_goal", goal),
    ):
        return fn(
            data.task,
            data.gold,
            data.signing.sign_collection(data.payload, data.key),
            data.key,
            data.pins,
        )


def test_insufficient_receipt_and_proven_subquote_satisfy_explicit_partial_contract(partial):
    unchanged = copy.deepcopy((partial.gold, partial.payload))
    assert evaluate(partial, old=True)["strict_correct"] is False
    result = evaluate(partial)
    assert result["strict_correct"] is True
    assert result["partial_evidence_scoring"]["insufficient_compatible_with_partial"] is True
    assert result["partial_evidence_scoring"]["rag_worker_completed"] is False
    assert result["partial_evidence_scoring"]["original_retrieval_expected"] == "complete"
    assert result["safety_violation"] is False
    assert (partial.gold, partial.payload) == unchanged


def test_completed_retrieval_with_partial_business_facts_is_still_accepted(partial):
    result = partial.payload["snapshot"]["state"]["results"]["1:documents"]
    result.update(status="succeeded", error=None)
    result["rag_completion"].update(verdict="semantic_retrieval")
    result["rag_completion"]["submission"]["outcome"] = "complete"
    partial.payload["snapshot"]["state"]["verifications"]["1:documents"].update(
        status="passed", error=None
    )
    rebind(partial)
    partial.payload["snapshot"]["report"]["claims"][0]["fact_coverage"]["fact_1"]["artifact_id"] = (
        partial.payload["snapshot"]["report"]["claims"][0]["documents"][0]["artifact_id"]
    )
    assert evaluate(partial)["strict_correct"] is True


def test_legacy_contract_is_not_silently_upgraded(partial):
    rebind(partial, policy="legacy")
    assert evaluate(partial)["strict_correct"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "proof",
        "missing_code",
        "invented_fact",
        "quote",
        "minimum_sources",
        "budget",
        "full_completion",
        "unsigned",
        "goal_hash",
        "artifact_hash",
        "no_scope_confirmation",
    ],
)
def test_partial_receipt_never_replaces_missing_safety_or_fact_requirements(partial, mutation):
    claim = partial.payload["snapshot"]["report"]["claims"][0]
    if mutation == "proof":
        claim["fact_coverage"]["fact_1"] = None
    elif mutation == "missing_code":
        partial.payload["snapshot"]["report"]["business_completion"]["missing_evidence"][
            "documents"
        ] = ["rag_task_insufficient"]
    elif mutation == "invented_fact":
        claim["fact_coverage"]["fact_2"] = copy.deepcopy(claim["fact_coverage"]["fact_1"])
    elif mutation == "quote":
        claim["documents"][0]["excerpt"] = "Invented financial promise."
    elif mutation == "minimum_sources":
        partial.gold.minimum_cited_sources = 2
    elif mutation == "budget":
        partial.payload["snapshot"]["usage"]["usage_complete"] = False
    elif mutation == "full_completion":
        partial.payload["snapshot"]["report"]["business_completion"].update(
            status="completed", verified_goals=["documents"], missing_evidence={}
        )
    elif mutation == "unsigned":
        record = partial.signing.sign_collection(partial.payload, partial.key)
        record["signature"] = "0" * 64
        with pytest.raises(ValueError, match="trusted collector"):
            partial.new_scorer.score(partial.task, partial.gold, record, partial.key, partial.pins)
        return
    elif mutation == "goal_hash":
        partial.payload["snapshot"]["state"]["results"]["1:documents"]["rag_completion"][
            "goal_sha256"
        ] = "9" * 64
    elif mutation == "artifact_hash":
        next(iter(partial.payload["artifacts"].values()))["source"] = "forged"
    else:
        rebind(partial, attested=False)
    try:
        assert evaluate(partial)["strict_correct"] is False
    except ValueError:
        pass


def test_host_opt_in_changes_only_policy_and_confirmation(partial):
    before = partial.scope.model_copy(deep=True)
    before.partial_evidence_policy = "legacy"
    fixed = confirm_partial_literals(
        before, partial.task.rag_scope, confirmation_ref="public-partial-policy-review"
    )
    assert fixed.partial_evidence_policy == "partial-facts-v1"
    assert fixed.question == before.question and fixed.metrics == before.metrics
    assert fixed.document_goal == before.document_goal
    assert fixed.goal_scope_attestation.confirmation_ref == "public-partial-policy-review"
