"""Public synthetic task contracts; no sealed inputs, Gold, database or provider I/O."""

import copy
import hashlib
import importlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact, Document, SearchResult
from datapilot.orchestration.rag_completion import goal_hash, retrieval_goal
from datapilot.reporting.contracts import CrossSourceReport, ReportScope


@pytest.fixture
def case(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    evaluator = importlib.import_module("p7_business_evaluator")
    signing = importlib.import_module("p7_business_scoring")
    pack = importlib.import_module("p7_holdout_pack")
    from test_p7_business_v2 import toy

    task, _ = toy()
    task = pack.CaseInput.model_validate_json(json.dumps(task))
    goal = retrieval_goal(task.document_goal.question)
    plan = {
        "tasks": [
            {"task_id": "documents", "worker": "rag", "instruction": task.question},
            {
                "task_id": "report",
                "worker": "report",
                "instruction": "Cite the evidence",
                "dependencies": ["documents"],
            },
        ],
    }
    artifact = Artifact(
        run_id="unit-rag",
        task_id="documents",
        plan_version=1,
        kind="documents",
        source="public-unit-fixture",
        documents=SearchResult(documents=[], fixture=True),
    ).model_dump(mode="json")
    ref = {"artifact_id": digest(artifact), "sha256": digest(artifact), "kind": "documents"}
    receipt = {
        "protocol": "rag-submit-v1",
        "call_id": "submit-unit",
        "submission": {"artifact_ids": [ref["artifact_id"]], "outcome": "unavailable"},
        "verdict": "empty",
        "goal_sha256": goal_hash(goal),
        "relevant_chunk_ids": [],
        "business_conclusions_verified": False,
    }
    model = {
        "data": {
            "tool_calls": [
                {
                    "id": receipt["call_id"],
                    "name": "submit_rag_result",
                    "args": receipt["submission"],
                },
            ]
        }
    }
    receipt["model_response_sha256"] = digest(model)
    error = {"code": "NO_RELEVANT_DOCUMENTS", "message": "No matches", "category": "tool"}
    result = {
        "run_id": "unit-rag",
        "task_id": "documents",
        "plan_version": 1,
        "worker": "rag",
        "status": "unavailable",
        "evidence_refs": [ref],
        "error": error,
        "rag_completion": receipt,
    }
    verified = {
        "task_id": "documents",
        "plan_version": 1,
        "status": "unavailable",
        "checks": ["identity", "capability", "evidence", "shape", "dependencies"],
        "error": error,
    }
    scope = {
        "owner": task.owner,
        "question": task.question,
        "datasets": {"bindings": []},
        "metrics": [],
        "document_goal": task.document_goal.model_dump(mode="json"),
        "causal_requested": False,
    }
    scope = ReportScope.model_validate_json(json.dumps(scope)).model_dump(mode="json")
    report = {
        "authorization_sha256": digest(scope),
        "authorization_scope": scope,
        "execution_status": "unavailable",
        "business_completion": {
            "status": "unavailable",
            "required_goals": ["documents"],
            "verified_goals": [],
            "missing_evidence": {"documents": ["document_evidence_insufficient"]},
        },
        "claims": [{"goal_id": "documents", "kind": "unavailable", "codes": ["empty"]}],
        "verified_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "markdown": "No evidence",
    }
    report = CrossSourceReport.model_validate_json(json.dumps(report)).model_dump(mode="json")
    tool = {"ordered_json": json.dumps({"rag_completion": receipt})}
    payload = {
        "case_id": task.case_id,
        "run_id": "unit-rag",
        "question_sha256": digest(task.question),
        "manifest": {
            "cross_source_report": {"scope": scope},
            "rag_scope": task.rag_scope.model_dump(mode="json"),
            "rag_completion_goal": goal,
        },
        "snapshot": {
            "unknown": False,
            "next": False,
            "review": False,
            "report": report,
            "state": {
                "run_id": "unit-rag",
                "question": task.question,
                "plan_version": 1,
                "plan": plan,
                "plan_history": {"1": copy.deepcopy(plan)},
                "reuse_origins": {},
                "results": {"1:documents": result},
                "verifications": {"1:documents": verified},
            },
        },
        "artifacts": {ref["artifact_id"]: artifact},
        "calls": [
            {
                "kind": "tool",
                "account": "1:documents",
                "tool_name": "submit_rag_result",
                "call_key": "tool:1:documents:submit-unit",
                "status": "complete",
                "payload": tool,
                "payload_hash": digest(tool),
            },
            {
                "kind": "model",
                "account": "1:documents",
                "tool_name": None,
                "call_key": "model:1:documents:public-unit",
                "status": "complete",
                "payload": model,
                "payload_hash": digest(model),
            },
        ],
    }
    gold = pack.Gold(
        case_id=task.case_id,
        business_completion="unavailable",
        host_decision="review_then_run",
        metrics=[],
        retrieval={"disposition": "insufficient", "facts": []},
        refusal_conditions=["document_evidence_insufficient"],
        causal_claim_must_remain_unverified=False,
    )
    return evaluator, signing, task, gold, payload


def evaluate(case):
    evaluator, signing, task, gold, payload = case
    key = b"public-test-signing-key-32-bytes!!"
    return evaluator.score(task, gold, signing.sign_collection(payload, key), key, source_hashes={})


def test_versioned_empty_receipt_satisfies_refusal_contract(case):
    # Same structural failure as bh2-030, without importing its sealed text or Gold.
    assert evaluate(case)["strict_correct"]


def replan(payload, *, reuse):
    state = payload["snapshot"]["state"]
    state["plan_version"] = 2
    state["plan_history"]["2"] = copy.deepcopy(state["plan"])
    result = copy.deepcopy(state["results"]["1:documents"])
    result.update(plan_version=2, reused_from="1:documents" if reuse else None)
    state["results"]["2:documents"] = result
    verified = copy.deepcopy(state["verifications"]["1:documents"])
    verified["plan_version"] = 2
    state["verifications"]["2:documents"] = verified
    if reuse:
        state["reuse_origins"]["2:documents"] = "1:documents"


def test_replan_explicit_verified_reuse_keeps_original_receipt(case):
    replan(case[-1], reuse=True)
    assert evaluate(case)["strict_correct"]


def test_fresh_current_version_wins_over_conflicting_same_id_history(case):
    payload = case[-1]
    replan(payload, reuse=False)
    state = payload["snapshot"]["state"]
    result = state["results"]["2:documents"]
    old_ref = result["evidence_refs"][0]
    artifact = copy.deepcopy(payload["artifacts"][old_ref["artifact_id"]])
    artifact["plan_version"] = 2
    h = digest(artifact)
    payload["artifacts"][h] = artifact
    result["evidence_refs"] = [{"artifact_id": h, "sha256": h, "kind": "documents"}]
    result["rag_completion"]["submission"]["artifact_ids"] = [h]
    model, tool = copy.deepcopy(payload["calls"][1]), copy.deepcopy(payload["calls"][0])
    model.update(account="2:documents", call_key="model:2:documents:public-unit")
    model["payload"]["data"]["tool_calls"][0]["args"] = result["rag_completion"]["submission"]
    model["payload_hash"] = digest(model["payload"])
    result["rag_completion"]["model_response_sha256"] = model["payload_hash"]
    tool.update(account="2:documents", call_key="tool:2:documents:submit-unit")
    tool["payload"] = {"ordered_json": json.dumps({"rag_completion": result["rag_completion"]})}
    tool["payload_hash"] = digest(tool["payload"])
    payload["calls"].extend([model, tool])
    state["results"]["1:documents"]["status"] = "failed"
    assert evaluate(case)["strict_correct"]


@pytest.mark.parametrize(
    "mutation",
    [
        "active_missing",
        "wrong_run",
        "wrong_task",
        "wrong_version",
        "wrong_worker",
        "missing_artifact",
        "artifact_hash",
        "foreign_artifact",
        "missing_verification",
        "forged_succeeded",
        "missing_receipt",
        "receipt_refs",
        "receipt_goal",
        "missing_call",
        "model_hash",
        "plan_worker",
        "plan_history",
        "unversioned_alias",
        "verification_version",
        "missing_refs",
        "duplicate_refs",
        "forged_passed",
    ],
)
def test_wrong_identity_or_missing_proof_is_rejected(case, mutation):
    payload = case[-1]
    state = payload["snapshot"]["state"]
    result = state["results"]["1:documents"]
    if mutation == "active_missing":
        replan(payload, reuse=True)
        del state["results"]["2:documents"]
    elif mutation in {"wrong_run", "wrong_task", "wrong_version", "wrong_worker"}:
        field, value = {
            "wrong_run": ("run_id", "foreign-run"),
            "wrong_task": ("task_id", "other"),
            "wrong_version": ("plan_version", 2),
            "wrong_worker": ("worker", "sql"),
        }[mutation]
        result[field] = value
    elif mutation == "missing_artifact":
        payload["artifacts"] = {}
    elif mutation == "artifact_hash":
        result["evidence_refs"][0]["sha256"] = "f" * 64
    elif mutation == "foreign_artifact":
        next(iter(payload["artifacts"].values()))["run_id"] = "foreign-run"
    elif mutation == "missing_verification":
        state["verifications"] = {}
    elif mutation == "forged_succeeded":
        result.update(status="succeeded", error=None)
    elif mutation == "missing_receipt":
        result["rag_completion"] = None
    elif mutation == "receipt_refs":
        result["rag_completion"]["submission"]["artifact_ids"] = ["f" * 64]
    elif mutation == "receipt_goal":
        result["rag_completion"]["goal_sha256"] = "f" * 64
    elif mutation == "missing_call":
        payload["calls"] = payload["calls"][1:]
    elif mutation == "model_hash":
        payload["calls"][1]["payload_hash"] = "f" * 64
    elif mutation == "plan_worker":
        state["plan"]["tasks"][0]["worker"] = "sql"
    elif mutation == "plan_history":
        state["plan_history"] = {}
    elif mutation == "verification_version":
        state["verifications"]["1:documents"]["plan_version"] = 2
    elif mutation == "missing_refs":
        result["evidence_refs"] = []
    elif mutation == "duplicate_refs":
        result["evidence_refs"] *= 2
    elif mutation == "forged_passed":
        result.update(status="succeeded", error=None)
        state["verifications"]["1:documents"].update(status="passed", error=None)
    else:
        state["results"]["documents"] = result
        del state["results"]["1:documents"]
    with pytest.raises(ValueError):
        evaluate(case)


@pytest.mark.parametrize(
    "mutation",
    [
        "no_reuse_grant",
        "changed_plan",
        "future_origin",
        "changed_result",
        "origin_verification_missing",
        "origin_verification_failed",
    ],
)
def test_replan_cannot_select_stale_or_unauthorized_same_id(case, mutation):
    payload = case[-1]
    replan(payload, reuse=True)
    state = payload["snapshot"]["state"]
    if mutation == "no_reuse_grant":
        state["reuse_origins"] = {}
    elif mutation == "changed_plan":
        state["plan"]["tasks"][0]["instruction"] = "Changed business goal"
        state["plan_history"]["2"] = copy.deepcopy(state["plan"])
    elif mutation == "future_origin":
        state["results"]["2:documents"]["reused_from"] = "3:documents"
        state["reuse_origins"]["2:documents"] = "3:documents"
    elif mutation == "origin_verification_missing":
        del state["verifications"]["1:documents"]
    elif mutation == "origin_verification_failed":
        state["verifications"]["1:documents"]["status"] = "failed"
    else:
        state["results"]["2:documents"]["error"]["message"] = "Unbound replacement"
    with pytest.raises(ValueError):
        evaluate(case)


def test_retrieval_completion_never_substitutes_for_business_completion(case):
    payload = case[-1]
    state = payload["snapshot"]["state"]
    old = state["results"]["1:documents"]
    artifact = Artifact(
        run_id="unit-rag",
        task_id="documents",
        plan_version=1,
        kind="documents",
        source="unit",
        documents=SearchResult(
            documents=[
                Document(
                    document_id="public-doc",
                    source="public.md",
                    version="v1",
                    text="public fact",
                    sha256=hashlib.sha256(b"public fact").hexdigest(),
                )
            ],
            fixture=True,
        ),
    ).model_dump(mode="json")
    h = digest(artifact)
    old.update(
        status="succeeded",
        error=None,
        evidence_refs=[
            {
                "artifact_id": h,
                "sha256": h,
                "kind": "documents",
            }
        ],
    )
    receipt = old["rag_completion"]
    receipt.update(verdict="semantic_retrieval", relevant_chunk_ids=["public-doc"])
    receipt["submission"] = {"artifact_ids": [h], "outcome": "complete"}
    payload["artifacts"] = {h: artifact}
    state["verifications"]["1:documents"].update(status="passed", error=None)
    model = payload["calls"][1]
    model["payload"]["data"]["tool_calls"][0]["args"] = receipt["submission"]
    model["payload_hash"] = digest(model["payload"])
    receipt["model_response_sha256"] = model["payload_hash"]
    tool = payload["calls"][0]
    tool["payload"] = {"ordered_json": json.dumps({"rag_completion": receipt})}
    tool["payload_hash"] = digest(tool["payload"])
    result = evaluate(case)
    assert result["rag_worker_complete"]
    assert not result["strict_correct"]  # A successful retrieval does not prove this refusal Gold.
