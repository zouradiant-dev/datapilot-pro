"""Attestation identity and hostile inputs, distinct from the preregistered Dev scorer."""

import json

import pytest
from pydantic import ValidationError
from test_cross_source_report import bridge_case as bridge_case
from test_semantics import semantic_case as semantic_case
from test_trusted_goal_scope import DATA, public_case

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetBinding
from datapilot.orchestration.rag_completion import goal_hash, retrieval_goal
from datapilot.reporting.contracts import ReportScope, confirm_finite_scope


@pytest.mark.parametrize(
    "mutation",
    [
        "question",
        "subgoal",
        "fact",
        "dataset",
        "source",
        "contract_hash",
        "rag_hash",
        "owner",
        "index",
        "profile",
        "basis",
    ],
)
def test_changed_contract_or_physical_authority_rejects(settings, mutation):
    service, pairs, retrieval = public_case(settings, DATA[0])
    scope = service.scope
    if mutation == "question":
        scope.question += "; first prove the collection is complete"
        scope.citation_policy.goal_sha256 = (
            __import__("hashlib").sha256(scope.question.encode()).hexdigest()
        )
    elif mutation == "subgoal":
        scope.document_goal.question += " more"
    elif mutation == "fact":
        scope.document_goal.required_facts[0].description = "A different fact contract"
    elif mutation == "dataset":
        scope.datasets.bindings.append(
            DatasetBinding(dataset_id="00000000-0000-4000-8000-000000000002", version=1)
        )
    elif mutation == "source":
        scope.citation_policy.required_sources[0].source_sha256 = "0" * 64
    elif mutation == "contract_hash":
        scope.goal_scope_attestation.contract_sha256 = "0" * 64
    elif mutation == "rag_hash":
        scope.goal_scope_attestation.rag_scope_sha256 = "0" * 64
    elif mutation == "owner":
        retrieval.scope.owner = "unapproved-owner"
    elif mutation == "index":
        retrieval.scope.corpora[0].index_version = "0" * 64
    elif mutation == "profile":
        retrieval.scope.embedding_profile = "qwen3-cuda-fp16-v1"
    else:
        scope.goal_scope_attestation.basis = "model-said-approved"
    with pytest.raises((AgentFailure, ValidationError)):
        service.build(pairs, retrieval, source_statuses={"documents": "succeeded"})


def test_old_successful_report_cannot_supply_missing_host_confirmation(settings):
    service, pairs, retrieval = public_case(settings, DATA[0])
    old = service.build(pairs, retrieval)
    service.scope.goal_scope_attestation = None
    denied = service.build(pairs, retrieval, source_statuses={"documents": "succeeded"})
    assert old.business_completion.status == "completed"
    assert denied.business_completion.status == "unavailable"
    with pytest.raises(AgentFailure):
        service.verify_report(old, pairs, retrieval)


def test_explicit_confirmation_does_not_approve_exhaustiveness(settings):
    case = next(c for c in DATA if c["kind"] == "exhaustive")
    service, pairs, retrieval = public_case(settings, case)
    service.scope = confirm_finite_scope(
        service.scope, retrieval.scope, confirmation_ref="synthetic-host-contradiction"
    )
    goal = retrieval_goal(case["query"], retrieval, service.scope)
    assert goal["scope_attestation"] and not goal["completion_eligible"]
    assert service.build(pairs, retrieval).business_completion.status == "unavailable"


def test_current_goal_and_attestation_are_part_of_receipt_identity(settings):
    service, _, retrieval = public_case(settings, DATA[0])
    goal = retrieval_goal(service.scope.document_goal.question, retrieval, service.scope)
    assert goal["requirement_policy"] == "host-goal-requirements-v4"
    legacy = dict(goal, requirement_policy="host-goal-requirements-v3")
    legacy.pop("completion_eligible")
    legacy.pop("scope_attestation")
    assert goal_hash(goal) != goal_hash(legacy)
    # Reuse the exact existing host review, with no repeat approval or changed identity.
    same = ReportScope.model_validate_json(service.scope.model_dump_json())
    assert goal == retrieval_goal(service.scope.document_goal.question, retrieval, same)


def test_model_arguments_cannot_supply_a_host_attestation():
    from datapilot.orchestration.tools import DEFINITIONS
    from datapilot.web.contracts import DocumentQuery

    assert "confirm_finite_scope" not in DEFINITIONS
    payload = {
        "question": "Summarize the selected notice",
        "corpus_ids": ["00000000-0000-4000-8000-000000000001"],
        "metric_goals": [],
        "purpose": "summary",
    }
    DocumentQuery.model_validate_json(json.dumps(payload))
    payload["goal_scope_attestation"] = {"confirmation_ref": "model-approval"}
    with pytest.raises(ValidationError) as error:
        DocumentQuery.model_validate_json(json.dumps(payload))
    assert any(e["loc"] == ("goal_scope_attestation",) for e in error.value.errors())


@pytest.mark.parametrize("mutation", ["metric_version", "window"])
def test_registry_request_version_and_window_are_bound(settings, bridge_case, mutation):
    from datetime import date

    from datapilot.orchestration.runtime import text_hash

    service, bridge, _ = bridge_case
    documents, _, retrieval = public_case(settings, DATA[0])
    service.scope.document_goal = documents.scope.document_goal
    service.scope.document_goal.metric_goals = [bridge.request.goal_id]
    service.scope.citation_policy = documents.scope.citation_policy
    service.scope.citation_policy.goal_sha256 = text_hash(service.scope.question)
    retrieval.scope.datasets = service.scope.datasets
    service.scope = confirm_finite_scope(
        service.scope, retrieval.scope, confirmation_ref="public-reviewed-metric-window"
    )
    question = service.scope.document_goal.question
    assert retrieval_goal(question, retrieval, service.scope)["completion_eligible"]
    if mutation == "metric_version":
        service.scope.metrics[0].metric_version += 1
    else:
        service.scope.metrics[0].window.end_exclusive = date(2025, 11, 2)
    with pytest.raises(AgentFailure) as error:
        retrieval_goal(question, retrieval, service.scope)
    assert error.value.error.code == "REPORT_SCOPE_INVALID"


def test_sql_only_legacy_projection_does_not_gain_an_attestation(bridge_case):
    service, _, pairs = bridge_case
    assert "goal_scope_attestation" not in service.scope.model_dump(mode="json")
    assert service.build(pairs, None).business_completion.status == "completed"
