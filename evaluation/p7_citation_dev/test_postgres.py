"""Explicit real PG/MCP revalidation of new Dev records, never paid inference."""

import json

import pytest
from candidate import project
from dev import OUT, OWNER, cases, environment, host_scope, source_ids

from datapilot.contracts import AgentFailure
from datapilot.orchestration.contracts import (
    Artifact,
    BudgetLimits,
    RagSubmission,
    TaskEnvelope,
    TaskSpec,
)
from datapilot.orchestration.runtime import ArtifactStore
from datapilot.persistence.session import run_async
from datapilot.rag.mcp import rag_session
from datapilot.reporting.service import report_session


@pytest.mark.parametrize("case_id", [f"cp{i:02}" for i in range(1, 13)])
def test_real_dev_revalidation_and_partial_safety(case_id):
    import os

    assert os.getenv("DATAPILOT_RUN_DB_TESTS") == "1"
    _, settings = environment()
    case = next(c for c in cases() if c["id"] == case_id)
    binding = json.loads((OUT / "bindings.json").read_bytes())["bindings"][case_id]
    row = next(
        r for r in json.loads((OUT / "observations.json").read_bytes()) if r["case_id"] == case_id
    )
    rag, scope = host_scope(case, binding)
    store = ArtifactStore("dev-" + case_id)
    pairs = []
    for payload in row["artifacts"]:
        artifact = Artifact.model_validate_json(json.dumps(payload))
        ref = store.put(artifact)
        if artifact.kind == "documents":
            pairs.append((ref, artifact))
    envelope = TaskEnvelope(
        run_id=store.run_id,
        plan_version=1,
        task=TaskSpec(task_id="documents", worker="rag", instruction=case["question"]),
        budget=BudgetLimits(),
        parent_id=store.run_id,
        allowed_tools=["search_documents", "submit_rag_result"],
    )
    submission = RagSubmission.model_validate_json(json.dumps(row["actual_submission"]))

    async def validate():
        async with rag_session(settings, rag, goal=case["question"]) as retrieval:
            async with report_session(settings, scope, scope.question, OWNER) as service:
                for _, artifact in pairs:
                    retrieval.validate_result(artifact.documents)
                if case_id == "cp08":
                    foreign = json.loads((OUT / "observations.json").read_bytes())[0]
                    mixed = pairs[0][1].documents.model_copy(deep=True)
                    foreign_doc = Artifact.model_validate_json(json.dumps(foreign["artifacts"][0]))
                    mixed.documents.append(foreign_doc.documents.documents[0])
                    with pytest.raises(AgentFailure):
                        retrieval.validate_result(mixed)
                metric_artifact = next(
                    (
                        Artifact.model_validate_json(json.dumps(a))
                        for a in row["artifacts"]
                        if a["kind"] == "metric"
                    ),
                    None,
                )
                if metric_artifact:
                    await service.refresh([metric_artifact])
                    assert metric_artifact.metric.verdict == "verified"
                view = project(
                    service,
                    pairs,
                    retrieval,
                    envelope,
                    store,
                    submission,
                    source_ids(case, binding),
                    metric=metric_artifact.metric if metric_artifact else None,
                )
                # Negative mixed-payload scenarios are deliberately blocked separately.
                if case_id not in {"cp08", "cp11"}:
                    assert view.model_dump(mode="json") == row["candidate"]
                if view.status == "completed":
                    assert not view.missing_facts and view.required_source_coverage == 1
                    assert view.receipt_outcome == "complete" and not scope.causal_requested
                if submission.outcome == "insufficient":
                    assert view.status != "completed"
                assert not view.causal_verified
                for field in ("index_version", "source_sha256", "version", "sha256"):
                    corrupt = pairs[0][1].documents.model_copy(deep=True)
                    if not corrupt.documents:
                        continue
                    setattr(corrupt.documents[0].citation, field, "0" * 64)
                    with pytest.raises(AgentFailure):
                        retrieval.validate_result(corrupt)
                    corrupted_artifact = pairs[0][1].model_copy(
                        update={"documents": corrupt}, deep=True
                    )
                    corrupted_ref = store.put(corrupted_artifact)
                    corrupted_pairs = [(corrupted_ref, corrupted_artifact)]
                    with pytest.raises(AgentFailure):
                        service.build(
                            corrupted_pairs, retrieval, source_statuses={"documents": "succeeded"}
                        )
                    bad_submission = submission.model_copy(
                        update={"artifact_ids": [corrupted_ref.artifact_id]}
                    )
                    with pytest.raises(AgentFailure):
                        project(
                            service,
                            corrupted_pairs,
                            retrieval,
                            envelope,
                            store,
                            bad_submission,
                            source_ids(case, binding),
                        )
                if metric_artifact:
                    changed = metric_artifact.metric.model_copy(deep=True)
                    changed.request.metric_version += 1
                    with pytest.raises(AgentFailure):
                        service.verify_metric(changed)

    run_async(validate())


def test_trials_preserve_scope_threshold_and_two_searches():
    rows = json.loads((OUT / "query-trials.json").read_bytes())
    assert len(rows) == 48
    for row in rows:
        assert 1 <= len(row["calls"]) <= 2
        for call in row["calls"]:
            result = call["result"]
            assert result["fixture"] is False and result["requested_top_k"] == 5
            assert all(d["citation"]["score"] >= 0.55 for d in result["documents"])


def test_new_durable_cross_process_evidence_budget_and_candidate_view():
    start = json.loads((OUT / "durable-start.json").read_bytes())
    for version in (11, 13):
        recovered = json.loads((OUT / f"durable-resume-py{version}.json").read_bytes())
        assert start == recovered
    assert start["candidate"]["status"] == "partial"
    assert start["candidate_durable_storage"] == "design_only_not_written"
    assert start["provider_calls"] == 0 and all(c["status"] == "complete" for c in start["calls"])
