"""Host finite-scope attestation for Final 50 current worker."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("evaluation/p7_v3_current").resolve()))
from current_worker import HOST_FINITE_CONFIRMATION_REF, host_confirm_reviewed_scope

from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import ReportScope


def _scope_and_rag(*, purpose="summary"):
    scope = ReportScope.model_validate(
        {
            "owner": "p7-chengyue-independent-v3",
            "question": "Public synthetic document question for host confirmation.",
            "datasets": {
                "bindings": [{"dataset_id": "00000000-0000-4000-8000-000000000001", "version": 1}]
            },
            "metrics": [],
            "document_goal": {
                "goal_id": "documents",
                "question": "Public synthetic document question for host confirmation.",
                "purpose": purpose,
                "metric_goals": [],
            },
            "causal_requested": False,
        }
    )
    rag = RagScope.model_validate(
        {
            "owner": "p7-chengyue-independent-v3",
            "datasets": scope.datasets.model_dump(mode="json"),
            "corpora": [
                {
                    "corpus_id": "00000000-0000-4000-8000-000000000002",
                    "index_version": "a" * 64,
                    "document_ids": ["b" * 64],
                }
            ],
        }
    )
    return scope, rag


def test_host_confirm_attests_reviewed_document_contract():
    scope, rag = _scope_and_rag()
    assert scope.goal_scope_attestation is None
    confirmed = host_confirm_reviewed_scope(scope, rag, {"authorization_binding": {}})
    assert confirmed.goal_scope_attestation is not None
    assert confirmed.goal_scope_attestation.confirmation_ref == HOST_FINITE_CONFIRMATION_REF
    assert confirmed.goal_scope_attestation.contract_sha256
    assert confirmed.goal_scope_attestation.rag_scope_sha256


def test_host_confirm_skips_sql_only_and_already_attested():
    scope, rag = _scope_and_rag()
    assert host_confirm_reviewed_scope(scope, None, {}) is scope
    sql = ReportScope.model_validate_json(
        json.dumps(
            {
                "owner": scope.owner,
                "question": scope.question,
                "datasets": scope.datasets.model_dump(mode="json"),
                "metrics": [
                    {
                        "goal_id": "metric_1",
                        "dataset_id": "00000000-0000-4000-8000-000000000001",
                        "dataset_version": 1,
                        "semantic_version": 1,
                        "metric_id": "paid_invoice_revenue",
                        "metric_version": 1,
                        "window": {"start": "2026-09-01", "end_exclusive": "2026-10-01"},
                        "intent": "measure",
                    }
                ],
                "causal_requested": False,
            }
        )
    )
    assert sql.document_goal is None
    assert host_confirm_reviewed_scope(sql, rag, {}) is sql
    once = host_confirm_reviewed_scope(scope, rag, {})
    twice = host_confirm_reviewed_scope(once, rag, {})
    assert twice.goal_scope_attestation == once.goal_scope_attestation


def test_host_confirm_prefers_binding_ref():
    scope, rag = _scope_and_rag()
    confirmed = host_confirm_reviewed_scope(
        scope,
        rag,
        {"authorization_binding": {"host_confirmation_ref": "host-reviewed-binding-ref"}},
    )
    assert confirmed.goal_scope_attestation.confirmation_ref == "host-reviewed-binding-ref"
