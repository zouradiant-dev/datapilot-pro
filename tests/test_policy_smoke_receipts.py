"""Public synthetic signed contracts; no private Smoke data, PostgreSQL or model calls."""

import copy
import importlib
import json

import pytest
from test_p7_scorer_versions import case as case

from datapilot.ingestion.common import digest


@pytest.fixture
def smoke_case(case):
    _, signing, task, _, payload = case
    core = importlib.import_module("p7_policy_smoke")
    scope = payload["manifest"]["cross_source_report"]["scope"]
    launch = core.Case.model_validate_json(
        json.dumps(
            {
                "case_id": "tps-03",
                "lane": "rag_only",
                "scope": scope,
                "rag_scope": task.rag_scope.model_dump(mode="json"),
            }
        )
    )
    payload["case_id"] = launch.case_id
    report = payload["snapshot"]["report"]
    report["rag_scope"] = launch.rag_scope.model_dump(mode="json")
    report["authorization_sha256"] = digest(
        {"report_scope": scope, "rag_scope_sha256": digest(launch.rag_scope)}
    )
    payload["snapshot"]["usage"] = {
        "calls": 2,
        "total_tokens": 30,
        "reported_tokens": 30,
        "usage_complete": True,
    }
    search = {
        "data": {
            "tool_calls": [
                {
                    "id": "search-unit",
                    "name": "search_documents",
                    "args": {"query": launch.document_goal.question, "top_k": 3},
                }
            ]
        }
    }
    payload["calls"].append(
        {
            "call_key": "model:1:documents:public-search",
            "kind": "model",
            "account": "1:documents",
            "status": "complete",
            "tool_name": None,
            "payload": search,
            "payload_hash": digest(search),
        }
    )
    payload["events"] = [{"tool_name": "search_documents", "tool_call_id": "search-unit"}]
    return core, signing, launch, payload


def failed(smoke_case, status="failed", omitted=False):
    core, signing, launch, payload = smoke_case
    state = payload["snapshot"]["state"]
    code = {"failed": "WORKER_LIMIT", "cancelled": "CANCELLED", "blocked": "DEPENDENCY_FAILED"}[
        status
    ]
    error = {"code": code, "category": "tool", "message": "Public synthetic task ended"}
    result = state["results"]["1:documents"]
    result.update(status=status, error=error, rag_completion=None)
    if omitted:
        result.pop("rag_completion")
    state["verifications"]["1:documents"].update(status="failed", error=error)
    report = payload["snapshot"]["report"]
    report["execution_status"] = "cancelled" if status == "cancelled" else "failed"
    report["business_completion"]["status"] = "blocked"
    payload["calls"][0]["payload"] = {"ordered_json": json.dumps({"error": error})}
    payload["calls"][0]["payload_hash"] = digest(payload["calls"][0]["payload"])
    return core, signing, launch, payload


def evaluate(value, expected="completed"):
    core, signing, launch, payload = value
    key = b"public-smoke-contract-unit-key-32!"
    gold = core.Gold(case_id=launch.case_id, completion=expected)
    return core.score(launch, gold, signing.sign_collection(payload, key), key)


@pytest.mark.parametrize("status", ["failed", "cancelled", "blocked"])
@pytest.mark.parametrize("omitted", [False, True])
def test_non_success_without_receipt_is_a_scored_failure(smoke_case, status, omitted):
    value = failed(smoke_case, status, omitted)
    before = copy.deepcopy(value[-1])
    result = evaluate(value)
    assert result["strict_correct"] is False
    assert result["rag_worker_status"] == status
    assert result["rag_receipt_verdict"] is None
    assert result["business_completion"] == "blocked"
    assert result["expected_completion"] == "completed"
    assert result["critical"] is False  # Known task failure is not a forged-source incident.
    assert value[-1] == before


def test_accepted_empty_receipt_keeps_its_real_verdict(smoke_case):
    result = evaluate(smoke_case, "unavailable")
    assert result["strict_correct"] is True
    assert result["rag_worker_status"] == "unavailable"
    assert result["rag_receipt_verdict"] == "empty"


@pytest.mark.parametrize("status", ["succeeded", "unavailable"])
def test_success_or_unavailable_cannot_omit_required_receipt(smoke_case, status):
    value = failed(smoke_case)
    p = value[-1]
    p["snapshot"]["state"]["results"]["1:documents"].update(
        status=status,
        error=None
        if status == "succeeded"
        else {"code": "EMPTY", "message": "None", "category": "tool"},
    )
    p["snapshot"]["state"]["verifications"]["1:documents"].update(
        status="passed" if status == "succeeded" else "unavailable",
        error=None
        if status == "succeeded"
        else {"code": "EMPTY", "message": "None", "category": "tool"},
    )
    with pytest.raises(ValueError, match="receipt"):
        evaluate(value)


@pytest.mark.parametrize(
    "mutation", ["identity", "version", "verification", "evidence", "scope", "unknown"]
)
def test_nullable_receipt_does_not_bypass_authority_or_evidence_checks(smoke_case, mutation):
    value = failed(smoke_case)
    p = value[-1]
    state = p["snapshot"]["state"]
    if mutation == "identity":
        state["results"]["1:documents"]["run_id"] = "other-run"
    elif mutation == "version":
        state["results"]["1:documents"]["plan_version"] = 2
    elif mutation == "verification":
        state["verifications"] = {}
    elif mutation == "evidence":
        p["artifacts"] = {}
    elif mutation == "scope":
        p["manifest"]["cross_source_report"]["scope"] = {"owner": "forged"}
    else:
        p["snapshot"]["unknown"] = True
    with pytest.raises(ValueError):
        evaluate(value)


def test_accepted_receipt_still_needs_the_matching_tool_call(smoke_case):
    smoke_case[-1]["snapshot"]["state"]["results"]["1:documents"]["rag_completion"]["call_id"] = (
        "forged-call"
    )
    with pytest.raises(ValueError, match="completion call"):
        evaluate(smoke_case, "unavailable")
