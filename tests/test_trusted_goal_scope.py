"""Public preregistered safety Dev; unit evidence doubles, never Live quality."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_report_causal_scope import document_case

from datapilot.orchestration.contracts import Artifact
from datapilot.orchestration.rag_completion import retrieval_goal
from datapilot.orchestration.runtime import ArtifactStore, text_hash
from datapilot.rag.contracts import Target
from datapilot.reporting import contracts
from datapilot.reporting.contracts import CitationPolicy, CitationSource, DocumentFact

DATA = json.loads(
    (Path(__file__).parent / "fixtures/rag/trusted-goal-scope-v4-r2.json").read_bytes()
)["cases"]


def confirmed(scope, rag, ref="public-synthetic-host-review-not-human-signature"):
    # Baseline can run on the retained v3 API; the final API is separately asserted.
    if hasattr(contracts, "confirm_finite_scope"):
        return contracts.confirm_finite_scope(scope, rag, confirmation_ref=ref)
    return scope


def public_case(settings, case):
    service, pairs, retrieval = document_case(settings, case["query"])
    old = pairs[0][1].documents.documents[0]
    result = pairs[0][1].documents.model_copy(deep=True)
    result.documents = []
    facts, sources = [], []
    for i, name in enumerate(case["required_sources"], 1):
        d = old.model_copy(deep=True)
        d.text = case["source_quote"] + f" 本条来源编号{i}。"
        d.source = name
        d.document_id = d.sha256 = text_hash(d.text)
        d.version = text_hash(name + d.text)
        c = d.citation
        c.source_id = text_hash(case["id"] + name)
        c.document_id = text_hash("document-" + case["id"] + name)
        c.version = c.source_sha256 = d.version
        c.chunk_id = c.sha256 = d.sha256
        c.start, c.end = 0, len(d.text)
        result.documents.append(d)
        facts.append(
            DocumentFact(
                fact_id=f"rule_{i}",
                description="Public preregistered literal rule",
                quotation=case["source_quote"],
                citation=c,
                confirmation_ref="public-synthetic-fact-review:" + case["id"],
            )
        )
        sources.append(CitationSource(**{k: getattr(c, k) for k in CitationSource.model_fields}))
    facts += [
        DocumentFact(fact_id=f"missing_{i + 1}", description="Not supported by the source")
        for i in range(case["missing_facts"])
    ]
    scope = service.scope
    scope.goal_scope_attestation = None  # A fact/fixture confirmation is not a goal review.
    scope.partial_evidence_policy = "partial-facts-v1"
    scope.document_goal.purpose = "facts"
    scope.document_goal.required_facts = facts
    scope.citation_policy = CitationPolicy(
        goal_sha256=text_hash(scope.question), required_sources=sources
    )
    pin = retrieval.scope.corpora[0]
    pin.document_ids = [d.citation.document_id for d in result.documents]
    retrieval.manifests[pin.corpus_id] = SimpleNamespace(
        target=Target(corpus_id=pin.corpus_id, owner=scope.owner),
        sources=[
            SimpleNamespace(
                source_id=d.citation.source_id,
                document_id=d.citation.document_id,
                version=d.version,
                text_sha256=d.version,
                name=d.source,
            )
            for d in result.documents
        ],
    )
    retrieval.validate_result = lambda r: all(d in result.documents for d in r.documents)
    store = ArtifactStore("scope-public-dev")
    ref = store.put(
        Artifact(
            run_id=store.run_id,
            task_id="documents",
            plan_version=1,
            kind="documents",
            source="explicit-unit-double",
            documents=result,
        )
    )
    if case["synthetic_host_confirmation"]:
        service.scope = confirmed(scope, retrieval.scope, "public-reviewed-contract:" + case["id"])
    return service, [(ref, store.get(ref))], retrieval


@pytest.mark.parametrize("case", DATA, ids=lambda c: c["id"])
def test_preregistered_scope_and_completion(settings, case):
    service, artifacts, retrieval = public_case(settings, case)
    goal = (
        retrieval_goal(case["query"], retrieval, service.scope)
        if hasattr(contracts, "confirm_finite_scope")
        else retrieval_goal(case["query"], retrieval)
    )
    report = service.build(artifacts, retrieval, source_statuses={"documents": "succeeded"})
    if folder := os.getenv("DATAPILOT_SCOPE_DIAGNOSTIC_OUT"):
        path = Path(folder) / (case["id"] + ".json")
        with path.open("x", encoding="utf-8") as f:
            json.dump(
                {
                    "id": case["id"],
                    "goal": goal,
                    "expected_requirement_class": case["expected_requirement_class"],
                    "report": report.model_dump(mode="json"),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
    assert report.business_completion.status == case["expected_report_status"]
    if hasattr(contracts, "confirm_finite_scope"):
        assert goal["completion_eligible"] is case["expected_completion_eligibility"]
        if case["expected_failure_reason"] == "goal_scope_not_attested":
            assert (
                "goal_scope_not_attested"
                in report.business_completion.missing_evidence["documents"]
            )
    service.verify_report(report, artifacts, retrieval, source_statuses={"documents": "succeeded"})
