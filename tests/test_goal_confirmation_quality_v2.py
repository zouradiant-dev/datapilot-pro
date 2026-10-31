"""Evaluator-layout regression using the actual public CreateTask shape."""

import pytest
from test_goal_confirmation_quality import KEY, fixture, sign_collection

from evaluation.goal_confirmation_quality import scoring, scoring_v2


def actual_contract():
    c, g, binding, data = fixture()
    req = data["message"]["goal_contract"]["review"]["request"]
    req.pop("dataset_id")
    req.pop("dataset_version")
    data["message"]["goal_contract"]["datasets"] = [binding["dataset"]]
    binding["semantic"] = {"semantic_version": 1}
    return c, g, binding, data


def test_original_layout_failure_is_retained_and_v2_scores_actual_contract():
    c, g, binding, data = actual_contract()
    signed = sign_collection(data, KEY)
    with pytest.raises(KeyError, match="dataset_id"):
        scoring.score(c, g, signed, KEY, binding)
    result = scoring_v2.score(c, g, signed, KEY, binding)
    assert result["technical_contract_correct"]
    assert result["semantic_equivalence"] == "NOT_VERIFIED"


@pytest.mark.parametrize("fault", ["dataset", "source_hash", "source_version", "unreviewed"])
def test_layout_repair_keeps_identity_and_no_auto_confirmation(fault):
    c, g, binding, data = actual_contract()
    goal = data["message"]["goal_contract"]
    if fault == "dataset":
        goal["datasets"][0] = {**binding["dataset"], "version": 2}
    elif fault == "source_hash":
        goal["sources"][0]["source_sha256"] = "0" * 64
    elif fault == "source_version":
        goal["sources"][0]["index_version"] = "0" * 64
    else:
        data["attestation_present"] = True
    result = scoring_v2.score(c, g, sign_collection(data, KEY), KEY, binding)
    assert result["technical_issues"] or result["safety_violations"]
