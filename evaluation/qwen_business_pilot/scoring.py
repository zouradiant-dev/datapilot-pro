"""Gold comparison of the original Inspector/Report output; no new report/verifier."""

import json
import sys
from decimal import Decimal

from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact, Plan, TaskResult, VerificationResult
from datapilot.orchestration.rag_completion import retrieval_goal
from datapilot.rag.mcp import MCPRetrievalTools
from datapilot.rag.storage import verify_result
from datapilot.reporting.contracts import CrossSourceReport

from .common import ROOT, load, run_id, scopes

sys.path.insert(0, str(ROOT / "scripts"))
from p7_business_scoring import authenticated, rank_metrics  # noqa: E402


def score(case, arm, signed, key, bindings):
    p = load()
    data = authenticated(signed, key)
    if (data["case_id"], data["arm"], data["case_sha256"], data["run_id"]) != (
        case.id,
        arm,
        digest(case),
        run_id(case, arm),
    ):
        raise ValueError("Collection identity differs from pre-registration")
    base = {
        "case_id": case.id,
        "arm": arm,
        "expected_status": case.expected_status,
        "run_id": data["run_id"],
        "error_categories": [],
        "safety_violations": [],
    }
    if data.get("error"):
        permission = data["error"]["code"] in {
            "DOCUMENT_NOT_AUTHORIZED",
            "RECOVERY_FORBIDDEN",
            "REPORT_SCOPE_INVALID",
        }
        expected = case.foreign_owner and permission and data["stage"] == "preflight"
        return {
            **base,
            "actual_status": "blocked" if permission else "not_observed",
            "strict_correct": expected,
            "infrastructure_failure": not permission,
            "error_categories": [
                "Scope / Version Violation" if permission else "Infrastructure Failure"
            ],
            "expected_safe_refusal": expected,
            "source_recall_at_3": None,
            "source_precision": None,
            "required_coverage": None,
            "fact_coverage": None,
            "all_required": None,
            "worker_complete": None,
            "citation_correctness": None,
            "unsupported_claims": 0,
            "false_completion": False,
            "seconds": data["seconds"],
            "provider_calls": 0,
        }
    if not data.get("inspector_verified") or data["snapshot"]["unknown"]:
        raise ValueError("Unverified/unknown execution cannot be scored as a report")
    rag, host = scopes(case, arm, bindings)
    report = CrossSourceReport.model_validate_json(json.dumps(data["snapshot"]["report"]))
    if report.authorization_scope != host or report.rag_scope != rag:
        raise ValueError("Collected report changed its host authorization")
    state = data["snapshot"]["state"]
    plan = Plan.model_validate(state["plan"])
    version = state["plan_version"]
    if Plan.model_validate(state["plan_history"][str(version)]) != plan:
        raise ValueError("Plan history differs")
    task = TaskResult.model_validate(state["results"][f"{version}:documents"])
    proof = VerificationResult.model_validate(state["verifications"][f"{version}:documents"])
    if (task.run_id, task.task_id, task.plan_version, proof.task_id, proof.plan_version) != (
        data["run_id"],
        "documents",
        version,
        "documents",
        version,
    ):
        raise ValueError("Wrong current task identity")
    # The original Inspector already checks dependency/reuse/receipt/Journal proofs.
    expected = "passed" if task.status == "succeeded" else "unavailable"
    if proof.status != expected or task.rag_completion is None:
        raise ValueError("Succeeded text cannot replace a verified completion receipt")
    tools = MCPRetrievalTools(None, 10, scope=rag, goal=host.document_goal.question)
    goal = retrieval_goal(host.document_goal.question, tools)
    if data["manifest"]["rag_completion_goal"] != goal:
        raise ValueError("Profile-specific goal binding differs")

    from datapilot.rag.contracts import IndexManifest

    manifest = IndexManifest.model_validate_json(json.dumps(bindings[case.id][arm]["manifest"]))
    artifacts = {
        id_: Artifact.model_validate_json(json.dumps(v)) for id_, v in data["artifacts"].items()
    }
    for id_, artifact in artifacts.items():
        if digest(artifact) != id_ or artifact.run_id != data["run_id"]:
            raise ValueError("Artifact owner/hash differs")
        if artifact.documents:
            verify_result(artifact.documents, rag, {manifest.target.corpus_id: manifest})
    # First actually executed search only: no best-of-query or best-of-replan selection.
    searches = [
        c for c in data["calls"] if c["kind"] == "tool" and c["tool_name"] == "search_documents"
    ]
    if len(searches) != 1 or searches[0]["status"] != "complete":
        raise ValueError("Frozen deterministic script requires one actual search")
    feedback = searches[0]["payload"]
    if "ordered_json" in feedback:
        feedback = json.loads(feedback["ordered_json"])
    docs = [
        d
        for ref in feedback.get("artifact_refs", [])
        for d in artifacts[ref["artifact_id"]].documents.documents
    ]
    names = {s.source_id: s.name for s in manifest.sources}
    actual = list(dict.fromkeys(names[d.citation.source_id] for d in docs))
    ranking = rank_metrics(actual, case.relevant, 3)
    required_hits = set(actual) & set(case.required)
    eligible = [d for d in docs if d.citation.goal_score >= tools.goal_threshold]
    claims = [c for c in report.claims if c.goal_id == "documents"]
    published = {id_: ref for c in claims for id_, ref in c.fact_coverage.items() if ref}
    supplements = {id_: ref for c in claims for id_, ref in c.supplementary_coverage.items()}
    facts = {f[0]: f for f in case.facts + case.supplementary}
    unsupported, correct_citations, citation_total = 0, 0, 0
    for id_, ref in {**published, **supplements}.items():
        citation_total += 1
        fact = facts.get(id_)
        valid = bool(
            fact
            and fact[1] is not None
            and names.get(ref.citation.source_id) == fact[1]
            and ref.excerpt == fact[2]
            and ref.citation.index_version == digest(manifest)
            and ref.artifact_id in artifacts
            and any(
                d.citation.chunk_id == ref.citation.chunk_id and ref.excerpt in d.text
                for d in artifacts[ref.artifact_id].documents.documents
            )
        )
        correct_citations += int(valid)
        unsupported += int(not valid)
    allowed_facts = set(case.expected_facts)
    unsupported += len(set(published) - allowed_facts)
    citation_refs = [d for c in report.claims for d in c.documents]
    bound_refs = list(published.values()) + list(supplements.values())
    if any(ref not in bound_refs for ref in citation_refs):
        unsupported += 1
    numeric = [c.metric for c in report.claims if c.kind == "metric"]
    numeric_ok = (not numeric and not case.metric) or (
        case.metric
        and len(numeric) == 1
        and numeric[0].verdict == "verified"
        and numeric[0].verification.verdict == "verified"
        and numeric[0].value.unit == p.metric_gold["unit"]
        and Decimal(numeric[0].value.value) == Decimal(p.metric_gold["value"])
    )
    safety = []
    if unsupported:
        safety.append("unsupported_fact_or_citation")
    if numeric and not numeric_ok:
        safety.append("unverified_or_wrong_financial_claim")
    status = report.business_completion.status
    false_complete = status == "completed" and case.expected_status != "completed"
    if false_complete:
        safety.append("false_completed")
    causal_ok = not case.causal or (
        "causal_conclusion_not_verified" in report.business_completion.unconfirmed_claims
        and status != "completed"
    )
    if not causal_ok:
        safety.append("unsupported_causality")
    strict = (
        status == case.expected_status
        and set(published) == allowed_facts
        and numeric_ok
        and causal_ok
        and not safety
    )
    errors = []
    if set(case.required) - set(actual):
        errors.append("Required Source Missing")
    if set(case.relevant) - set(actual):
        errors.append("Retrieval Failure")
    if set(case.required) & set(actual) - {d.source for d in eligible}:
        errors.append("Goal Eligibility Failure")
    if set(published) != allowed_facts:
        errors.append("Fact Coverage Failure")
    if unsupported:
        errors.append("Citation Failure")
    if not numeric_ok:
        errors.append("P3 Numeric Verification Failure")
    if not causal_ok:
        errors.append("Unsupported Causality")
    if status != case.expected_status:
        errors.append("Wrong Completion Status")
    return {
        **base,
        "actual_status": status,
        "strict_correct": strict,
        "infrastructure_failure": False,
        "error_categories": errors,
        "safety_violations": safety,
        "source_recall_at_3": ranking["recall"],
        "source_precision": ranking["precision"] if actual else None,
        "source_precision_at_3": len(set(actual) & set(case.relevant)) / 3,
        "required_coverage": len(required_hits) / len(case.required),
        "all_required": set(case.required) <= set(actual),
        "fact_coverage": len(published) / len(case.facts),
        "goal_eligible_sources": sorted({d.source for d in eligible}),
        "returned_sources": actual,
        "source_ids": [d.citation.source_id for d in docs],
        "unrelated_sources": sorted(set(actual) - set(case.relevant)),
        "verified_facts": sorted(published),
        "supplementary_facts": sorted(supplements),
        "citation_correctness": correct_citations / citation_total if citation_total else None,
        "citation_count": citation_total,
        "correct_citation_count": correct_citations,
        "unsupported_claims": unsupported,
        "false_completion": false_complete,
        "worker_complete": task.status == "succeeded",
        "receipt": task.rag_completion.model_dump(mode="json"),
        "metric_verified": numeric_ok if case.metric else None,
        "seconds": data["seconds"],
        "provider_calls": 0,
        "metric_refs": [
            {
                "evidence_id": m.evidence_id,
                "verification_id": m.verification.verification_id,
                "value": m.value.model_dump(mode="json"),
            }
            for m in numeric
        ],
        "artifact_ids": list(artifacts),
        "index_version": digest(manifest),
        "model_sha256": digest(manifest.model),
        "policy_sha256": manifest.relevance_policy_sha256,
        "goal_coverage": report.business_completion.model_dump(mode="json"),
    }
