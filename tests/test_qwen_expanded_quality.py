"""Expanded evaluation contracts, pairing/inference, signature and data independence guards."""

import copy
import sys

import pytest
from pydantic import ValidationError

from evaluation.qwen_expanded_quality.common import ROOT, Case, cases, order, run_id
from evaluation.qwen_expanded_quality.summarize import paired

sys.path.insert(0, str(ROOT / "scripts"))
from p7_business_scoring import authenticated, sign_collection  # noqa: E402


def test_exact_100_stratified_20_80_and_distinct_ids():
    rows = cases()
    assert len(rows) == 100 and len(order("dev")) == 20 and len(order("validation")) == 80
    assert set(c.id for c in order("dev")).isdisjoint(c.id for c in order("validation"))
    assert {c.expected_status for c in rows} == {"completed", "partial", "unavailable", "blocked"}
    assert len({run_id(c, a) for c in rows for a in ["bge", "qwen"]}) == 200


@pytest.mark.parametrize("kind", ["id", "quote", "metric", "facts"])
def test_bad_case_cannot_change_gold_silently(kind):
    data = copy.deepcopy(cases()[80 if kind == "metric" else 0].model_dump())
    if kind == "id":
        data["id"] = "qc06"
    if kind == "quote":
        data["facts"][0][2] = "Not in source"
    if kind == "metric":
        data["metric_input"]["value"] = "1.00"
    if kind == "facts":
        data["expected_facts"] = ["forged"]
    with pytest.raises(ValidationError):
        Case.model_validate(data)


@pytest.mark.parametrize("field", ["run_id", "arm", "case_sha256", "result"])
def test_unsigned_edits_never_become_quality_results(field):
    key = b"only a public synthetic unit key" * 2
    signed = sign_collection({"run_id": "one", "arm": "bge", "case_sha256": "x", "result": {}}, key)
    signed["payload"][field] = "forged succeeded"
    with pytest.raises(ValueError):
        authenticated(signed, key)


def test_paired_inference_does_not_impute_not_run_or_count_unpaired():
    rows = [
        {
            "bge": {"observed": True, "strict_correct": False},
            "qwen": {"observed": True, "strict_correct": True},
        },
        {"bge": {"observed": False}, "qwen": {"observed": True, "strict_correct": True}},
    ]
    result = paired(rows, False)
    assert result["observed_complete_pairs"] == 1
    assert result["primary_95_paired_bootstrap_interval"] is None
    assert result["bge_wrong_qwen_right"] == 1 and result["exact_mcnemar_two_sided"] is None


def test_paired_bootstrap_frozen_seed_is_reproducible():
    rows = [
        {
            "bge": {"observed": True, "strict_correct": i % 2 == 0},
            "qwen": {"observed": True, "strict_correct": True},
        }
        for i in range(10)
    ]
    assert paired(rows, True) == paired(rows, True)
