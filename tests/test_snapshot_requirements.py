"""Snapshot eligibility is independent of retrieval success and budget admission."""

import pytest
from test_report_causal_scope import document_case

from datapilot.orchestration.rag_completion import retrieval_goal


@pytest.mark.parametrize(
    "question",
    [
        "基于已经固定的最新文档快照检索规则。",
        "分析同一时点快照中的经营变化。",
        "Analyze the latest fixed document snapshot.",
        "Use a consistent cross-source snapshot.",
    ],
)
def test_latest_or_global_snapshot_is_unattested_even_if_model_calls_it_fixed(question):
    goal = retrieval_goal(question)
    assert goal["unsupported_requirements"]
    assert goal["unsupported_reason"] == "snapshot_not_attested"


@pytest.mark.parametrize(
    "question",
    [
        "在宿主已授权的固定索引版本上检索运营背景。",
        "Retrieve background from the host-authorized pinned index version.",
        "检索包含“最新快照”的文档片段，保留实际来源引用",
    ],
)
def test_pinned_read_or_literal_locator_does_not_claim_global_freshness(question):
    assert not retrieval_goal(question)["unsupported_requirements"]
    assert "unsupported_reason" not in retrieval_goal(question)


def test_report_exposes_snapshot_refusal_instead_of_hiding_it_as_missing_fact(settings):
    service, pairs, retrieval = document_case(settings, "分析宿主已固定的最新文档快照。")
    report = service.build(pairs, retrieval)
    assert report.business_completion.status == "unavailable"
    assert report.business_completion.missing_evidence["documents"] == ["snapshot_not_attested"]
    assert "宿主未证明" in report.markdown and not report.charts


@pytest.mark.parametrize("missing", ["index_version", "document_ids"])
def test_snapshot_words_cannot_supply_missing_trusted_source_identity(missing):
    from uuid import uuid4

    from pydantic import ValidationError

    from datapilot.rag.contracts import CorpusPin

    raw = {"corpus_id": str(uuid4()), "index_version": "a" * 64, "document_ids": ["b" * 64]}
    raw.pop(missing)
    with pytest.raises(ValidationError):
        CorpusPin.model_validate(raw)


def test_model_cannot_pass_a_snapshot_authorization_argument():
    from pydantic import ValidationError

    from datapilot.orchestration.tools import SearchArguments

    with pytest.raises(ValidationError):
        SearchArguments(query="latest snapshot", top_k=5, snapshot_id="invented")
