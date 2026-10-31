"""Compatibility contracts without CUDA, local weights, private bindings or a paid API."""

from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.rag_completion import retrieval_goal
from datapilot.rag.contracts import RagScope
from datapilot.rag.models import specification, validate_vectors
from datapilot.rag.qwen import QwenEmbedding
from datapilot.rag.qwen import specification as qwen_spec
from datapilot.rag.storage import chunk_table, search_threshold
from evaluation.qwen_migration import select_threshold


def test_legacy_scope_hash_and_goal_projection_are_unchanged():
    scope = RagScope(allow_saas=True)
    old = {
        "owner": "local-user",
        "corpora": [],
        "datasets": {"bindings": []},
        "allow_saas": True,
        "min_score": 0.55,
    }
    assert scope.model_dump(mode="json") == old
    assert digest(scope) == digest(old)
    assert specification().dimensions == 512
    assert retrieval_goal("How can billing statements be exported?") == retrieval_goal(
        "How can billing statements be exported?", SimpleNamespace()
    )


@pytest.mark.parametrize("profile", ["qwen3-cpu-v1", "qwen3-cuda-fp16-v1"])
def test_native_profile_and_scope_are_explicit(profile):
    value = qwen_spec(profile)
    assert value.dimensions == 1024 and len(value.files) == 6
    assert RagScope(embedding_profile=profile).model_dump()["embedding_profile"] == profile
    assert value != specification()


def test_cpu_and_gpu_indexes_cannot_share_a_recipe():
    assert qwen_spec("qwen3-cpu-v1") != qwen_spec("qwen3-cuda-fp16-v1")


@pytest.mark.parametrize("profile", ["fake", "../../python.exe", "bge-new-threshold"])
def test_unknown_host_profile_is_rejected(profile):
    with pytest.raises(ValidationError):
        RagScope(embedding_profile=profile)
    with pytest.raises(AgentFailure):
        qwen_spec(profile)


@pytest.mark.parametrize("dimension", [512, 1024])
def test_native_vector_validation_and_closed_table_names(dimension):
    matrix = np.zeros((1, dimension), dtype=np.float32)
    matrix[0, 0] = 1
    validate_vectors(matrix, 1, dimension)
    assert chunk_table(dimension) == ("rag.chunks" if dimension == 512 else "rag.chunks_1024")
    with pytest.raises(AgentFailure):
        validate_vectors(matrix, 1, 1024 if dimension == 512 else 512)


def test_arbitrary_dimension_cannot_select_a_physical_table():
    with pytest.raises(AgentFailure):
        chunk_table("1024; DROP TABLE rag.chunks")


def test_host_goal_policy_is_explicit_and_retains_requirements():
    trusted = SimpleNamespace(relevance_policy="independent-dev-goal-policy", goal_threshold=0.8)
    goal = retrieval_goal("查找至少两份文档：维护冻结的规定", trusted)
    assert goal["minimum_sources"] == 2
    assert goal["relevance_policy"] == trusted.relevance_policy
    assert goal["minimum_goal_score"] == 0.8
    assert not goal["business_conclusions_verified"]
    assert retrieval_goal("普通问题")["relevance_policy"] == "bge-host-goal-cosine-v1"


def test_threshold_selection_cannot_read_validation_or_accept_empty_input():
    for rows in [[], [{"split": "validation"}]]:
        with pytest.raises(ValueError):
            select_threshold(rows, [0.6])


def test_search_and_goal_calibration_are_separate():
    rows = [
        {
            "split": "calibration",
            "relevant": ["a"],
            "goal_relevant": [],
            "ranked": [("a", 0.8)],
            "goals": [("a", 0.7)],
        }
    ]
    assert select_threshold(rows, [0.6, 0.75, 0.85]) == 0.75
    assert select_threshold(rows, [0.6, 0.75, 0.85], goal=True) == 0.85
    with pytest.raises(ValueError):
        select_threshold(rows, [0.6], goal=True)


def test_no_truncation_or_oversized_batch_before_model_access():
    model = object.__new__(QwenEmbedding)
    for texts in [["x" * 513], ["x"] * 1025, [None]]:
        with pytest.raises(AgentFailure, match="quota"):
            model.encode(texts)


def test_qwen_policy_is_not_a_bge_alias_and_host_cannot_lower_calibrated_floor():
    from datapilot.rag.mcp import MCPRetrievalTools
    from datapilot.rag.qwen import policy

    question = "Which approval is needed for a workspace freeze?"
    scope = RagScope(embedding_profile="qwen3-cuda-fp16-v1", min_score=0)
    tools = MCPRetrievalTools(None, 10, scope=scope, goal=question)
    assert tools.relevance_policy != retrieval_goal(question)["relevance_policy"]
    assert search_threshold(scope) == policy(scope.embedding_profile)["search_threshold"]
    assert search_threshold(scope.model_copy(update={"min_score": 0.9})) == 0.9
    citation = SimpleNamespace(goal_sha256=tools.goal_sha256, goal_score=0.99)
    docs = [SimpleNamespace(citation=citation)]
    assert tools.qualifying_documents(docs, retrieval_goal(question, tools)) == docs
    assert not tools.qualifying_documents(docs, retrieval_goal(question))


def test_bge_rejects_qwen_tokenizer_instead_of_mislabeling_legacy_vectors(monkeypatch):
    from datapilot.rag import models

    monkeypatch.setattr(models.importlib.metadata, "version", lambda name: "0.22.2")
    with pytest.raises(AgentFailure, match="original locked runtime"):
        models.LocalEmbedding()
