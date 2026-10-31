"""Versioned three-policy Dev contracts; original Runtime and business verifier stay unchanged."""

import json
from collections import Counter
from decimal import Decimal

from p7_business_evaluator import rag_result
from p7_business_scoring import authenticated
from p7_policy_smoke_worker import POLICY as POLICY
from p7_policy_smoke_worker import PROFILE as PROFILE
from p7_policy_smoke_worker import permit_valid as permit_valid
from p7_smoke_pack import runtime_files
from pydantic import BaseModel, ConfigDict, Field, model_validator

from datapilot.ingestion.common import digest
from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import CrossSourceReport, ReportScope


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: str = Field(pattern=r"^tps-0[1-8]$")
    lane: str = Field(pattern=r"^(sql_only|rag_only|sql_rag)$")
    scope: ReportScope
    rag_scope: RagScope | None
    preflight_denial: str | None = None

    @model_validator(mode="after")
    def explicit_lane_and_authority(self):
        if bool(self.scope.metrics) != (self.lane != "rag_only"):
            raise ValueError("Lane must describe actual metric goals")
        if bool(self.scope.document_goal) != (self.lane != "sql_only"):
            raise ValueError("Lane must describe actual document goal")
        if self.scope.document_goal and (
            self.rag_scope is None or self.rag_scope.owner != self.scope.owner
        ):
            raise ValueError("Explicit matching host document authority required")
        return self

    @property
    def document_goal(self):
        return self.scope.document_goal

    @property
    def question(self):
        return self.scope.question


class Gold(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    case_id: str = Field(pattern=r"^tps-0[1-8]$")
    completion: str = Field(pattern=r"^(completed|partial|unavailable|blocked)$")
    metrics: dict = Field(default_factory=dict)
    proved_facts: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    supplements: list[str] = Field(default_factory=list)
    allowed_documents: list[str] = Field(default_factory=list)
    forbidden_documents: list[str] = Field(default_factory=list)
    known_quality_limitation: bool = False


def check_freeze(root, manifest):
    snapshot_root = root / manifest["snapshot"]
    if snapshot_root.is_symlink() or not snapshot_root.resolve().is_relative_to(root.resolve()):
        raise ValueError("Frozen snapshot escapes its workspace")
    if runtime_files(root) != manifest["files"]:
        raise ValueError("FREEZE_INVALIDATED: exact runtime/build closure changed")
    for name, expected in manifest["files"].items():
        frozen = snapshot_root / name
        if frozen.is_symlink() or not frozen.is_file():
            raise ValueError("Frozen source missing or symlinked")
        from p7_holdout_pack import sha

        if sha(frozen.read_bytes()) != expected:
            raise ValueError("Frozen source bytes changed")
    extra = {
        p.relative_to(root / manifest["snapshot"]).as_posix()
        for p in (root / manifest["snapshot"]).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    if extra != set(manifest["files"]):
        raise ValueError("Frozen closure has unexpected files")


def score(case, gold, signed, key):
    payload = authenticated(signed, key)
    if payload["case_id"] != case.case_id or gold.case_id != case.case_id:
        raise ValueError("Wrong case identity")
    if payload["question_sha256"] != digest(case.question):
        raise ValueError("Wrong question identity")
    if case.preflight_denial:
        ok = (
            payload.get("stage") == "preflight"
            and payload.get("code") == case.preflight_denial
            and payload.get("case_sha256") == digest(case)
            and payload.get("model_mode") == "not_invoked"
        )
        return {
            "case_id": case.case_id,
            "strict_correct": ok,
            "business_completion": "blocked",
            "model_calls": 0,
            "host_refusal": True,
            "critical": not ok,
        }
    manifest = payload["manifest"]
    if digest(manifest["cross_source_report"]["scope"]) != digest(case.scope) or manifest.get(
        "rag_scope"
    ) != (case.rag_scope.model_dump(mode="json") if case.rag_scope else None):
        raise ValueError("Full policy scope or document authority changed")
    snapshot = payload["snapshot"]
    if snapshot["unknown"] or snapshot["next"] or snapshot["review"] or not snapshot["report"]:
        raise ValueError("Incomplete or unknown collection cannot be scored as terminal")
    report = CrossSourceReport.model_validate_json(json.dumps(snapshot["report"]))
    if report.authorization_scope != case.scope or report.rag_scope != case.rag_scope:
        raise ValueError("Report authority differs from the exact launch")
    if report.authorization_sha256 != digest(
        {
            "report_scope": case.scope.model_dump(mode="json"),
            "rag_scope_sha256": digest(case.rag_scope) if case.rag_scope else None,
        }
    ):
        raise ValueError("Report authorization hash differs")
    claims = {c.goal_id: c for c in report.claims}
    numeric = []
    requests = {r.goal_id: r for r in case.scope.metrics}
    for goal, expected in gold.metrics.items():
        bridge = claims[goal].metric if goal in claims else None
        if bridge and (
            bridge.verdict != "verified"
            or bridge.verification.verdict != "verified"
            or bridge.verification_sha256 != digest(bridge.verification)
            or bridge.verification.evidence_id != bridge.evidence_id
            or bridge.verification.request_sha256 != digest(requests[goal])
            or not any(
                digest(a.get("metric")) == digest(bridge) and digest(a) == key
                for key, a in payload["artifacts"].items()
            )
        ):
            raise ValueError("P3 proof is not the collected verified Artifact")
        numeric.append(
            bool(
                bridge
                and bridge.verdict == "verified"
                and bridge.verification.verdict == "verified"
                and bridge.request == requests[goal]
                and bridge.source_sha256 == expected["source_sha256"]
                and bridge.context.semantic_sha256 == expected["semantic_sha256"]
                and bridge.context.metric_sha256 == expected["metric_sha256"]
                and bridge.value.unit == expected["unit"]
                and Decimal(bridge.value.value) == Decimal(expected["value"])
            )
        )
    docs = [d for c in report.claims for d in c.documents]
    for reference in docs:
        artifact = payload["artifacts"][reference.artifact_id]
        if digest(artifact) != reference.artifact_id or artifact["run_id"] != payload["run_id"]:
            raise ValueError("Document Artifact hash/identity differs")
        actual = [
            d
            for d in artifact["documents"]["documents"]
            if d["citation"]["chunk_id"] == reference.citation.chunk_id
        ]
        if len(actual) != 1 or actual[0]["citation"] != reference.citation.model_dump(mode="json"):
            raise ValueError("Published citation is not the actual retrieved fragment")
        if reference.excerpt not in actual[0]["text"]:
            raise ValueError("Published quotation differs from source text")
    allowed = set(gold.allowed_documents)
    citation_safe = all(d.citation.document_id in allowed for d in docs)
    coverage = {k: v for c in report.claims for k, v in c.fact_coverage.items()}
    supplements = {k: v for c in report.claims for k, v in c.supplementary_coverage.items()}
    facts = all(coverage.get(k) is not None for k in gold.proved_facts)
    missing_codes = {
        v for codes in report.business_completion.missing_evidence.values() for v in codes
    }
    missing = all(
        coverage.get(k) is None and "document_fact_unverified:" + k in missing_codes
        for k in gold.missing_facts
    )
    supplement_ok = all(k in supplements for k in gold.supplements)
    causal_safe = not case.scope.causal_requested or (
        "causal_conclusion_not_verified" in report.business_completion.unconfirmed_claims
    )
    original = True
    rag = rag_result(payload, case) if case.document_goal else None
    if case.document_goal:
        searches = [e for e in payload["events"] if e.get("tool_name") == "search_documents"]
        if searches:
            first = searches[0]["tool_call_id"]
            calls = [
                c
                for row in payload["calls"]
                if row["kind"] == "model"
                for c in (row["payload"] or {}).get("data", {}).get("tool_calls", [])
                if c["id"] == first and c["name"] == "search_documents"
            ]
            original = len(calls) == 1 and calls[0]["args"]["query"] == case.document_goal.question
        else:
            original = False
    usage = snapshot["usage"]
    child_calls = Counter(
        c["account"] for c in payload["calls"] if c["kind"] == "model" and c["account"] != "root"
    )
    budget = (
        usage["usage_complete"]
        and usage["calls"] <= 8
        and usage["total_tokens"] <= 18000
        and all(c["status"] == "complete" for c in payload["calls"])
        and all(count <= 4 for count in child_calls.values())
    )
    correct = (
        report.business_completion.status == gold.completion
        and all(numeric)
        and citation_safe
        and facts
        and missing
        and supplement_ok
        and causal_safe
        and original
        and budget
    )
    return {
        "case_id": case.case_id,
        "strict_correct": correct,
        "business_completion": report.business_completion.status,
        "expected_completion": gold.completion,
        "numeric_correct": all(numeric) if numeric else None,
        "citations_authorized_and_relevant": citation_safe,
        "fact_coverage_correct": facts and missing,
        "supplements_correct": supplement_ok,
        "causal_safe": causal_safe,
        "original_first_query": original if case.document_goal else None,
        "budget_known": budget,
        "model_calls": usage["calls"],
        "tokens": usage["total_tokens"],
        "rag_worker_status": rag["status"] if rag else None,
        "rag_receipt_verdict": (
            rag["rag_completion"]["verdict"] if rag and rag["rag_completion"] is not None else None
        ),
        "critical": not (citation_safe and causal_safe and budget),
        "known_quality_limitation": gold.known_quality_limitation,
    }
