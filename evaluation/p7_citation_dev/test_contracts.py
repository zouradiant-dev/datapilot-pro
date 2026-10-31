"""Public synthetic contracts/doubles; these are not retrieval or model quality tests."""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from candidate import citation_policy, project  # noqa: E402
from test_document_fact_coverage import fact, synthetic  # noqa: E402

from datapilot.config import Settings  # noqa: E402
from datapilot.contracts import AgentFailure  # noqa: E402
from datapilot.orchestration.contracts import (  # noqa: E402
    BudgetLimits,
    RagSubmission,
    TaskEnvelope,
    TaskSpec,
)
from datapilot.orchestration.runtime import ArtifactStore  # noqa: E402


def sample(*, two_sources=False, confirmed=True, causal=False):
    settings = Settings(_env_file=None, llm_mode="fake")
    service, pairs, retrieval = synthetic(
        settings, text="视频录制自动生成双语字幕。外发影片是否需要水印尚未规定。", purpose="facts"
    )
    service.scope.question = service.scope.document_goal.question = (
        "视频录制的字幕与外发水印规则是什么？" + ("至少两份文档。" if two_sources else "")
    )
    service.scope.causal_requested = causal
    service.scope.document_goal.required_facts = [
        fact(pairs, "captions", "自动生成双语字幕" if confirmed else None),
        fact(pairs, "watermark"),
    ]
    store = ArtifactStore(pairs[0][1].run_id)
    ref = store.put(pairs[0][1])
    pairs = [(ref, store.get(ref))]
    envelope = TaskEnvelope(
        run_id=store.run_id,
        plan_version=1,
        task=TaskSpec(task_id="documents", worker="rag", instruction=service.scope.question),
        allowed_tools=["search_documents", "submit_rag_result"],
        budget=BudgetLimits(),
        parent_id=store.run_id,
    )
    submission = RagSubmission(artifact_ids=[ref.artifact_id], outcome="insufficient")
    sources = {pairs[0][1].documents.documents[0].citation.source_id}
    if two_sources:
        sources.add("absent-second-required-source")
    return service, pairs, retrieval, envelope, store, submission, sources


@pytest.mark.parametrize("supplement", [False, True])
def test_required_source_cannot_be_replaced_by_supplement(supplement):
    result = citation_policy(
        {"required"}, {"supplement"}, {"supplement"}, allow_supplements=supplement
    )
    assert not result["accepted"] and result["required_coverage"] == 0


def test_required_only_and_grounded_supplement_are_distinct_proposals():
    assert not citation_policy({"r"}, {"r", "s"})["accepted"]
    result = citation_policy({"r"}, {"r", "s"}, {"s"}, allow_supplements=True)
    assert result["accepted"] and result["status"] == "PENDING_OWNER_ADJUDICATION"


def test_unrelated_authorized_background_still_fails_citation_policy():
    assert not citation_policy({"r"}, {"r", "garden"}, {"s"}, allow_supplements=True)["accepted"]


def test_no_empty_set_precision_or_coverage_percentage():
    result = citation_policy(set(), set())
    assert result["precision"] is None and result["required_coverage"] is None


def test_baseline_loses_but_dev_view_preserves_only_literal_supported_part():
    args = sample()
    service, _, retrieval, *_ = args
    baseline = service.build([], retrieval, source_statuses={"documents": "unavailable"})
    result = project(*args)
    assert baseline.business_completion.status == "unavailable"
    assert result.status == "partial" and result.receipt_outcome == "insufficient"
    assert result.supported_facts == ["captions"] and result.missing_facts == ["watermark"]
    assert result.mode == "dev_projection_only" and not result.causal_verified


def test_insufficient_two_source_contract_stays_incomplete_without_losing_first_fact():
    args = sample(two_sources=True)
    result = project(*args)
    assert result.required_source_coverage == 0.5 and result.status == "partial"
    assert "required_source_missing" in result.missing
    args[5].outcome = "complete"
    with pytest.raises(AgentFailure) as error:
        project(*args)
    assert error.value.error.code == "EVIDENCE_INSUFFICIENT"


def test_nonempty_related_text_with_no_proof_does_not_publish_business_fact():
    result = project(*sample(confirmed=False))
    assert not result.supported_facts and result.status == "unavailable"


def test_causal_background_cannot_become_causal_conclusion():
    result = project(*sample(causal=True))
    assert result.status == "partial" and not result.causal_verified
    assert "causal_conclusion_not_verified" in result.missing


@pytest.mark.parametrize("field", ["index_version", "source_sha256", "sha256", "version"])
def test_wrong_pin_or_hash_fails_closed(field):
    args = sample()
    artifact = args[1][0][1].model_copy(deep=True)
    setattr(artifact.documents.documents[0].citation, field, "f" * 64)
    ref = args[4].put(artifact)
    args[1][:] = [(ref, artifact)]
    args[5].artifact_ids = [ref.artifact_id]
    with pytest.raises(AgentFailure):
        project(*args)


def test_wrong_artifact_hash_and_wrong_task_identity_are_rejected():
    args = sample()
    args[1][0][0].sha256 = "a" * 64
    with pytest.raises(AgentFailure):
        project(*args)


def test_changed_quotation_is_not_verified():
    args = sample()
    args[0].scope.document_goal.required_facts[0].quotation = "自动生成十九种字幕"
    result = project(*args)
    assert result.status == "unavailable" and result.supported_facts == []


@pytest.mark.parametrize(
    "field,value", [("run_id", "another-run"), ("task_id", "other"), ("plan_version", 2)]
)
def test_other_run_task_or_plan_cannot_supply_partial_evidence(field, value):
    args = sample()
    artifact = args[1][0][1].model_copy(update={field: value}, deep=True)
    with pytest.raises(AgentFailure):
        ref = args[4].put(artifact)
        args[1][:] = [(ref, artifact)]
        args[5].artifact_ids = [ref.artifact_id]
        project(*args)


def test_extra_or_unselected_artifact_cannot_bypass_receipt():
    args = sample()
    args[5].artifact_ids = ["f" * 64]
    with pytest.raises(AgentFailure):
        project(*args)


def test_missing_confirmation_cannot_be_mistaken_for_host_proof():
    args = sample()
    value = args[0].scope.document_goal.required_facts[0].model_dump(mode="json")
    value["confirmation_ref"] = None
    with pytest.raises(ValidationError):
        type(args[0].scope.document_goal.required_facts[0]).model_validate(value)


def test_plain_document_background_cannot_be_a_verified_p3_metric():
    with pytest.raises(AttributeError):
        project(*sample(), metric=object())
