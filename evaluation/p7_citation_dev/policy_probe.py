"""New public Dev only: original source proof checks, separate proposed citation policy."""

import json

from candidate import citation_policy
from dev import OUT, cases, environment, host_scope, source_ids
from v3_common import write_new

from datapilot.contracts import AgentFailure
from datapilot.orchestration.contracts import Artifact
from datapilot.orchestration.runtime import ArtifactStore
from datapilot.persistence.session import run_async
from datapilot.rag.mcp import rag_session
from datapilot.reporting.contracts import DocumentFact, DocumentReference
from datapilot.reporting.service import fact_coverage, report_session


async def probe():
    _, settings = environment()
    bindings = json.loads((OUT / "bindings.json").read_bytes())["bindings"]
    records = {r["case_id"]: r for r in json.loads((OUT / "observations.json").read_bytes())}
    case = next(c for c in cases() if c["id"] == "cp09")
    rag, scope = host_scope(case, bindings["cp09"])
    artifact = Artifact.model_validate_json(json.dumps(records["cp09"]["artifacts"][0]))
    store = ArtifactStore(artifact.run_id)
    ref = store.put(artifact)
    documents = [
        DocumentReference(artifact_id=ref.artifact_id, citation=d.citation, excerpt=d.text)
        for d in artifact.documents.documents
    ]
    doc = next(d for d in documents if "整MiB" in d.excerpt)
    fact = DocumentFact(
        fact_id="rounding",
        description="Display rounding supplements capacity units",
        citation=doc.citation,
        quotation="展示值向上取整到整MiB",
        confirmation_ref="synthetic-host-dev-claim-binding-not-owner-policy-approval",
    )
    goal = scope.document_goal.model_copy(update={"required_facts": [fact]}, deep=True)
    async with rag_session(settings, rag, goal=case["question"]) as retrieval:
        retrieval.validate_result(artifact.documents)
    supported = fact_coverage(goal, documents)["rounding"]
    assert supported is not None
    required = source_ids(case, bindings["cp09"])
    published = {d.citation.source_id for d in documents}
    supplementary = {supported.citation.source_id}
    accepted = citation_policy(required, published, supplementary, allow_supplements=True)
    assert accepted["accepted"] and not citation_policy(required, published)["accepted"]
    # A plausible description and real hash cannot replace an actually supported quote.
    forged = goal.model_copy(deep=True)
    forged.required_facts[0].quotation = "展示值从不取整"
    assert fact_coverage(forged, documents)["rounding"] is None
    assert not citation_policy(required, supplementary, supplementary, allow_supplements=True)[
        "accepted"
    ]

    case = next(c for c in cases() if c["id"] == "cp10")
    rag, scope = host_scope(case, bindings["cp10"])
    async with rag_session(settings, rag, goal=case["question"]) as retrieval:
        primary = await retrieval.search(case["question"], 5)
        background = await retrieval.search("果园夏季滴灌和桃树修剪", 5)
        assert any(d.source == "orchard.md" for d in background.documents)
        store = ArtifactStore("cp10-policy-two-searches")
        pairs = []
        for result in (primary, background):
            ref = store.put(
                Artifact(
                    run_id=store.run_id,
                    task_id="documents",
                    plan_version=1,
                    kind="documents",
                    source="two-search-public-dev",
                    documents=result,
                )
            )
            pairs.append((ref, store.get(ref)))
        async with report_session(settings, scope, scope.question, scope.owner) as service:
            report = service.build(pairs, retrieval, source_statuses={"documents": "succeeded"})
        cited = [d for claim in report.claims for d in claim.documents]
        irrelevant = next(d for d in background.documents if d.source == "orchard.md")
        assert irrelevant.citation.source_id not in {d.citation.source_id for d in cited}
        assert report.business_completion.status == "completed"
        bad_set = {d.citation.source_id for d in cited} | {irrelevant.citation.source_id}
        denied = citation_policy(
            source_ids(case, bindings["cp10"]), bad_set, allow_supplements=True
        )
        assert not denied["accepted"]
        foreign = artifact.documents.model_copy(deep=True)
        foreign.documents = [*primary.documents, artifact.documents.documents[0]][:5]
        try:
            retrieval.validate_result(foreign)
        except AgentFailure:
            mixed_foreign_rejected = True
        else:
            raise AssertionError("Mixed foreign corpus accepted")
    write_new(
        OUT / "claim-policy-probe.json",
        {
            "policy_status": "PENDING_OWNER_ADJUDICATION",
            "provider_calls": 0,
            "claim_binding": {
                "claim_id": "storage_display_rounding",
                "fact": fact.model_dump(mode="json"),
                "supported": True,
                "source_class": "acceptable_supplement_candidate",
            },
            "required_only": citation_policy(required, published),
            "grounded_supplement": accepted,
            "forged_quote_rejected": True,
            "supplement_does_not_replace_required": True,
            "unrelated_retrieved_but_not_published": irrelevant.citation.model_dump(mode="json"),
            "unrelated_policy": denied,
            "mixed_foreign_rejected": mixed_foreign_rejected,
            "real_mcp_searches": 2,
            "top_k": 5,
            "threshold": 0.55,
        },
    )
    print("Real claim grounding, unrelated-background filtering and mixed-scope rejection passed")


if __name__ == "__main__":
    run_async(probe())
