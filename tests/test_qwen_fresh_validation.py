"""No new Validation output inspection: input, isolation, signatures and inference only."""

import copy
import sys

import pytest
from pydantic import ValidationError

from evaluation.qwen_fresh_validation.common import BASE, OUT, ROOT, Case, cases, order, run_id
from evaluation.qwen_fresh_validation.summarize import impl

sys.path.insert(0, str(ROOT / "scripts"))
from p7_business_scoring import authenticated, sign_collection  # noqa: E402


def test_fresh_inputs_have_100_cases_20_80_all_states_and_new_ids():
    rows = cases()
    assert len(rows) == 100 and len(order("dev")) == 20 and len(order("validation")) == 80
    assert set(c.id for c in order("dev")).isdisjoint(c.id for c in order("validation"))
    assert {c.expected_status for c in rows} == {"completed", "partial", "unavailable", "blocked"}
    assert len({run_id(c, a) for c in rows for a in ("bge", "qwen")}) == 200
    assert sum(c.preflight is not None for c in rows) == 4


@pytest.mark.parametrize("field", ["id", "facts", "numeric", "quote"])
def test_invalid_gold_or_quote_cannot_silently_pass_contract(field):
    raw = copy.deepcopy(cases()[80 if field == "numeric" else 0].model_dump())
    if field == "id":
        raw["id"] = "ex001"
    elif field == "facts":
        raw["expected_facts"] = ["invented"]
    elif field == "numeric":
        raw["metric_input"]["value"] = "999999.99"
    else:
        raw["facts"][0][2] = "Not in original source"
    with pytest.raises(ValidationError):
        Case.model_validate(raw)


@pytest.mark.parametrize("field", ["run_id", "case_sha256", "arm", "result"])
def test_unsigned_changes_cannot_become_evidence_or_success(field):
    key = b"public fixture test signing key" * 2
    bundle = sign_collection(
        {"run_id": "new", "case_sha256": "gold", "arm": "bge", "result": {}}, key
    )
    bundle["payload"][field] = "forged succeeded"
    with pytest.raises(ValueError):
        authenticated(bundle, key)


def test_private_evaluation_modules_do_not_redirect_historical_artifacts():
    from evaluation.qwen_expanded_quality import common as old

    assert BASE.OUT == OUT and old.OUT != OUT and old.BASE.OUT == old.OUT
    assert "fresh-v3" not in old.run_id(old.cases()[0], "bge")


def test_partial_pairs_never_receive_primary_inference():
    p = [
        {
            "bge": {"observed": True, "strict_correct": False},
            "qwen": {"observed": True, "strict_correct": True},
        },
        {"bge": {"observed": False}, "qwen": {"observed": True, "strict_correct": True}},
    ]
    result = impl.paired(p, False)
    assert result["observed_complete_pairs"] == 1
    assert result["primary_95_paired_bootstrap_interval"] is None
    assert result["exact_mcnemar_two_sided"] is None


def test_no_hidden_gold_or_permissions_added_to_model_tools():
    # Dataset/Corpus rights remain original host Scope, never fields in model Search schema.
    from datapilot.orchestration.tools import SearchArguments

    assert set(SearchArguments.model_fields) == {"query", "top_k"}
