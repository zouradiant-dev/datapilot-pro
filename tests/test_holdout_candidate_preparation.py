"""New Holdout uses repaired scoring without approving or dispatching draft contracts."""

from copy import deepcopy

import pytest

from evaluation.p7_v3_current.holdout_preparation import LANES, bind_drafts


@pytest.fixture
def public_drafts():
    return [
        {"id": f"g2-bh-{prefix}-{i:03}", "lane": lane, "question": f"Public synthetic control {i}"}
        for lane, prefix in LANES.items()
        for i in range(1, 21)
    ]


@pytest.fixture
def candidate():
    return {
        "tree_sha256": "a" * 64,
        "scoring_profiles": {
            "partial-facts-v1": {
                "version": "p7-current-partial-evidence-v3",
                "file": "evaluation/p7_v3_current/partial_evidence_scorer.py",
                "sha256": "b" * 64,
            }
        },
    }


def test_all_new_drafts_bind_repaired_scorer_without_implicit_approval(public_drafts, candidate):
    original = deepcopy(public_drafts)
    result = bind_drafts(public_drafts, candidate)
    assert result["planned"] == 60
    assert {case["scorer_version"] for case in result["cases"]} == {
        "p7-current-partial-evidence-v3"
    }
    assert (
        sum(case["partial_evidence_policy"] == "HOST_REVIEW_REQUIRED" for case in result["cases"])
        == 40
    )
    assert all(case["dispatch"] == "NOT_RUN" for case in result["cases"])
    assert result["formal_launch_ready"] is result["live_allowed"] is False
    assert public_drafts == original


@pytest.mark.parametrize("change", ["legacy-id", "duplicate", "missing-case", "old-scorer"])
def test_draft_binding_rejects_old_identity_or_scoring(public_drafts, candidate, change):
    if change == "legacy-id":
        public_drafts[0]["id"] = "p7-holdout-v3-011"
    elif change == "duplicate":
        public_drafts[1]["id"] = public_drafts[0]["id"]
    elif change == "missing-case":
        public_drafts.pop()
    else:
        candidate["scoring_profiles"]["partial-facts-v1"]["version"] = "old-scorer"
    with pytest.raises(ValueError):
        bind_drafts(public_drafts, candidate)
