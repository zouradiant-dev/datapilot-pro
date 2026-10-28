"""Approval manifest contracts over tiny synthetic proposals; never writes Registry."""

import copy
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("p7_p3_confirmation_request")


def proposals(module):
    dataset_id = "11111111-1111-4111-8111-111111111111"
    semantics = []
    metrics = []
    for version, amount in ((1, "major"), (2, None)):
        semantic = {"entities": [{"entity": "invoices", "amount_storage": amount}]}
        metric = {"currency": "CNY", "metric_id": "paid_invoice_revenue"}
        semantics.append(
            {
                "semantic_version": version,
                "definition": semantic,
                "sha256": module.sha(module.canonical(semantic)),
            }
        )
        metrics.append(
            {
                "metric_id": "paid_invoice_revenue",
                "metric_version": version,
                "semantic_version": version,
                "definition": metric,
                "sha256": module.sha(module.canonical(metric)),
            }
        )
    pins = {
        "datasets": {
            "precision": {
                "dataset_id": dataset_id,
                "dataset_version": 1,
                "source_sha256": "a" * 64,
                "semantic_definitions": semantics,
                "metric_definitions": metrics,
            }
        }
    }
    cases = [
        {
            "case_id": id_,
            "metrics": [
                {
                    "dataset_id": dataset_id,
                    "dataset_version": 1,
                    "semantic_version": version,
                    "metric_version": version,
                    "metric_id": "paid_invoice_revenue",
                }
            ],
        }
        for id_, version in (("public-a", 1), ("public-b", 1), ("public-negative", 2))
    ]
    return cases, pins


def test_dedup_exact_identity_and_never_auto_approve(module):
    cases, pins = proposals(module)
    original = copy.deepcopy(pins)
    entries = module.group_definitions(cases, pins, {c["case_id"] for c in cases})
    assert len(entries) == 4 and pins == original
    assert all(
        not e["register_allowed_by_this_request"] and e["approval_status"] == "pending"
        for e in entries
    )
    normal = [e for e in entries if e["category"].startswith("A_")]
    assert len(normal) == 2 and all(
        e["affected_case_ids"] == ["public-a", "public-b"] for e in normal
    )


def test_unknown_unit_and_dependency_are_excluded_not_filled(module):
    cases, pins = proposals(module)
    entries = module.group_definitions(cases, pins, {c["case_id"] for c in cases})
    excluded = [e for e in entries if e["category"].startswith("C_")]
    assert len(excluded) == 2
    semantic = next(e for e in excluded if e["identity"]["kind"] == "semantic")
    assert semantic["definition"]["entities"][0]["amount_storage"] is None


def test_conflicting_content_cannot_share_a_registry_version(module):
    cases, pins = proposals(module)
    forged = copy.deepcopy(pins["datasets"]["precision"]["metric_definitions"][0])
    forged["sha256"] = "f" * 64
    pins["datasets"]["precision"]["metric_definitions"].append(forged)
    with pytest.raises(ValueError, match="conflicting"):
        module.group_definitions(cases, pins, {"public-a"})
