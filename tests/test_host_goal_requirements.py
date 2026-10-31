"""Pre-registered public classification cases, no model or database inference."""

import json
from pathlib import Path

import pytest

from datapilot.ingestion.common import digest
from datapilot.orchestration.rag_completion import goal_hash, retrieval_goal

DATA = json.loads(
    (Path(__file__).parent / "fixtures/rag/host-goal-requirements-v2.json").read_bytes()
)


@pytest.mark.parametrize("case", DATA["cases"], ids=lambda c: c["id"])
def test_preregistered_requirement_boundary(case):
    goal = retrieval_goal(case["query"])
    assert goal["unsupported_requirements"] == case["unsupported"], case["classification"]
    assert goal["question_sha256"]
    assert goal["business_conclusions_verified"] is False


def test_requirement_policy_is_part_of_goal_and_receipt_identity():
    goal = retrieval_goal(DATA["e2e"]["query"])
    assert goal["requirement_policy"] == "host-goal-requirements-v4"
    old = {k: v for k, v in goal.items() if k != "requirement_policy"}
    assert goal_hash(goal) != goal_hash(old) and digest(goal) != digest(old)


def test_required_source_count_and_literal_terms_remain_host_bound():
    assert retrieval_goal("查找至少两份文档中的所有权规则")["minimum_sources"] == 2
    literal = retrieval_goal("检索包含“所有文档”的文档片段，保留来源引用")
    assert literal["required_terms"] == ["所有文档"]
    assert not literal["unsupported_requirements"]
