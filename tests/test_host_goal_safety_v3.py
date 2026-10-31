"""Pre-registered public safety Dev, not a new blind business benchmark."""

import json
from pathlib import Path

import pytest

from datapilot.orchestration.rag_completion import goal_hash, retrieval_goal

DATA = json.loads(
    (Path(__file__).parent / "fixtures/rag/host-goal-requirements-v3.json").read_bytes()
)


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda c: c["id"])
def test_registered_behavior(case):
    goal = retrieval_goal(case["query"])
    assert goal["unsupported_requirements"] == case["unsupported"]
    assert goal["business_conclusions_verified"] is False


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda c: c["id"])
def test_registered_classification(case):
    goal = retrieval_goal(case["query"])
    assert goal["requirement_class"] == case["expected_class"]
    assert goal["requirement_policy"] == "host-goal-requirements-v4"


def test_new_requirement_identity_cannot_be_replaced_by_old_receipt():
    goal = retrieval_goal(DATA["e2e"]["query"])
    legacy = {k: v for k, v in goal.items() if k != "requirement_class"}
    legacy["requirement_policy"] = "host-goal-requirements-v2"
    assert goal_hash(goal) != goal_hash(legacy)


@pytest.mark.parametrize(
    "query",
    [
        "遍历所有文档无需核对费用。",
        "遍历所有文档不需要检查其他文件。",
        "无需扫描整个语料而必须核对每份文件。",
        "List all confirmed documents.",
        "列出所有已知文档。",
        "Inspect every verified source.",
    ],
)
def test_negation_of_another_action_or_known_source_never_proves_completeness(query):
    assert retrieval_goal(query)["unsupported_requirements"] is True


@pytest.mark.parametrize(
    "query,unsupported",
    [
        ("遍历所有内容，核对沙盒导出审批。", True),
        ("检查全部内容。", True),
        ("展示完整内容。", True),
        ("不要求遍历全部内容，只解释已确认的审批事实。", False),
    ],
)
def test_original_content_collection_guard_and_negation(query, unsupported):
    assert retrieval_goal(query)["unsupported_requirements"] == unsupported


@pytest.mark.parametrize(
    "case", [c for c in DATA["cases"] if c["unsupported"]], ids=lambda c: c["id"]
)
async def test_real_source_and_model_success_cannot_attest_goal_completeness(settings, case):
    from test_rag_completion import run

    result, _, _, _ = await run(
        settings, ["search", "complete", "insufficient"], question=case["query"], related=True
    )
    assert result["completion"].status != "completed"
    task = result["results"]["1:rag"]
    assert task.rag_completion.submission.outcome == "insufficient"
    assert task.rag_completion.business_conclusions_verified is False
