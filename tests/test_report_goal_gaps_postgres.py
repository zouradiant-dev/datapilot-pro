"""Isolated PG/MCP/journal/Collector controls; public data and scripted decisions only."""

import hashlib
import json
import os
import secrets
from pathlib import Path
from uuid import uuid4

import pytest
from test_cross_source_postgres import ReportDecisions
from test_cross_source_postgres import report_data as report_data
from test_rag_postgres import embedding as embedding
from test_semantic_integration import metric_data as metric_data

from datapilot.db.management import management_url
from datapilot.ingestion.common import digest
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import ChunkCitation
from datapilot.rag.storage import Repository
from datapilot.reporting.contracts import (
    CitationPolicy,
    CitationSource,
    DocumentFact,
    DocumentGoal,
    ReportScope,
    UnboundMetricGoal,
    confirm_finite_scope,
)
from datapilot.semantics.repository import MetricRepository
from evaluation.p7_v3_current.holdout_contracts import HoldoutAnswer, HoldoutCase
from evaluation.p7_v3_current.holdout_scoring import score

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("DATAPILOT_RUN_DB_TESTS") != "1", reason="Isolated PG opt-in"),
]


@pytest.mark.parametrize("kind", ["unbound", "evidence_only", "source_context"])
def test_native_goal_gaps_keep_p3_journal_and_signed_scoring(
    pg_settings, report_data, metric_data, kind
):
    from p7_business_runtime import collect
    from p7_business_scoring import sign_collection

    schema, _, request, rag = report_data
    req = request("mrr" if kind == "evidence_only" else "paid_invoice_revenue")
    reader = Repository(management_url("rag_reader"), rag)
    try:
        manifests = reader.manifests()
    finally:
        reader.close()
    manifest = next(iter(manifests.values()))
    source = next(s for s in manifest.sources if s.name == "billing.md")
    text = (Path(__file__).parent / "fixtures/reporting/billing.md").read_text(encoding="utf-8")
    quote = "账单收款不是经常性订阅收入，退款与未支付账单不可猜测纳入。"
    start = text.index(quote)
    chunk = next(c for c in source.chunks if c.start <= start and start + len(quote) <= c.end)
    pin = rag.corpora[0]
    citation = ChunkCitation(
        **chunk.model_dump(),
        corpus_id=pin.corpus_id,
        index_version=pin.index_version,
        source_id=source.source_id,
        document_id=source.document_id,
        version=source.version,
        source_sha256=source.text_sha256,
        model_revision=manifest.model.revision,
        chunker_sha256=digest(manifest.chunker),
        score=0.0,
    )
    question = (
        "核验订阅指标并保留账单规程引用。"
        if kind == "evidence_only"
        else "核验收入并引用账单规则，同时索取尚未确认的另一个指标。"
    )
    query = "引用账单规程中已付款收入与订阅收入、未支付账单的区别。"
    scope = ReportScope(
        question=question,
        datasets=rag.datasets,
        metrics=[req],
        document_goal=DocumentGoal(
            goal_id="documents",
            question=query,
            metric_goals=[req.goal_id],
            purpose="facts",
            independent_facts=True,
            evidence_only=kind == "evidence_only",
            required_facts=[
                DocumentFact(
                    fact_id="billing_boundary",
                    description="Public billing rule",
                    citation=citation,
                    quotation=quote,
                    confirmation_ref="public-native-host-review",
                )
            ],
        ),
        unbound_metric_goals=[
            UnboundMetricGoal(
                goal_id="pending_metric",
                description="A separate requested metric with no confirmed definition",
                reason="definition_missing",
            )
        ]
        if kind == "unbound"
        else [],
        citation_policy=CitationPolicy(
            goal_sha256=hashlib.sha256(question.encode()).hexdigest(),
            required_sources=[
                CitationSource(**{k: getattr(citation, k) for k in CitationSource.model_fields})
            ],
        ),
    )
    if kind == "source_context":
        question = query = (
            "引用账单规程，说明文档是否给出退款到账时限；未提供时保留来源引文并明确无法核验。"
        )
        scope = ReportScope(
            question=question,
            datasets=rag.datasets,
            metrics=[],
            partial_evidence_policy="partial-facts-v1",
            document_goal=DocumentGoal(
                goal_id="documents",
                question=question,
                metric_goals=[],
                purpose="facts",
                required_facts=[
                    DocumentFact(fact_id="refund_deadline", description="退款到账时限")
                ],
                retain_source_context=True,
            ),
        )
    scope = confirm_finite_scope(scope, rag, confirmation_ref="public-native-finite-goal-review")
    cid = "g2-bh-rag-020" if kind == "source_context" else "g2-bh-xsrc-020"
    run_id = str(uuid4())
    case = HoldoutCase.model_validate_json(
        json.dumps(
            {
                "case_id": cid,
                "lane": "rag_only" if kind == "source_context" else "sql_rag",
                "objective": "Public native contract control",
                **scope.model_dump(
                    mode="json",
                    include={
                        "owner",
                        "question",
                        "datasets",
                        "metrics",
                        "document_goal",
                        "causal_requested",
                    },
                ),
                "report_scope": scope.model_dump(mode="json"),
                "rag_scope": rag.model_dump(mode="json"),
            }
        )
    )
    config = {
        "case_id": cid,
        "run_id": run_id,
        "owner": scope.owner,
        "question_sha256": digest(question),
        "report_scope": scope.model_dump(mode="json"),
        "rag_scope": rag.model_dump(mode="json"),
    }

    class Insufficient(ReportDecisions):
        async def respond(self, messages, tools):
            reply = await super().respond(messages, tools)
            for call in reply.tool_calls:
                if call["name"] == "submit_rag_result":
                    call["args"]["outcome"] = "insufficient"
            return reply

    async def execute():
        result = await run_durable(
            pg_settings,
            run_id,
            question,
            report_scope=scope,
            rag_scope=rag,
            transport=Insufficient(query) if kind == "source_context" else ReportDecisions(query),
        )
        return result, await collect(config, pg_settings, scope, rag)

    result, payload = run_async(execute())
    report = result["cross_source_report"]
    assert report is not None and not payload["snapshot"]["unknown"]
    expected = "partial" if kind == "unbound" else "unavailable"
    assert report.business_completion.status == expected
    assert next(c for c in report.claims if c.kind == "context").documents
    if kind == "source_context":
        assert report.business_completion.verified_goals == []
        assert report.business_completion.satisfied_evidence_goals == []
        assert next(c for c in report.claims if c.kind == "context").fact_coverage == {
            "refund_deadline": None
        }
        expected_codes = {}
        metric_gold = None
    elif kind == "evidence_only":
        assert report.business_completion.verified_goals == []
        assert report.business_completion.satisfied_evidence_goals == ["documents"]
        metric_gold = {
            "goal_id": req.goal_id,
            "disposition": "unavailable",
            "unit": "CNY/month",
            "reason": "mrr_definition_missing",
        }
        expected_codes = {req.goal_id: ["mrr_definition_missing"]}
    else:
        assert "pending_metric" in report.business_completion.missing_evidence
        assert not any(k.endswith(":pending_metric") for k in result["results"])
        assert "pending_metric" not in {t.task_id for t in result["plan"].tasks}
        metric_gold = {
            "goal_id": req.goal_id,
            "disposition": "verified",
            "unit": "CNY",
            "value": "300",
        }
        expected_codes = {"pending_metric": ["definition_missing"]}
    gold = HoldoutAnswer.model_validate_json(
        json.dumps(
            {
                "case_id": cid,
                "business_completion": expected,
                "host_decision": "review_then_run",
                "metrics": [metric_gold] if metric_gold else [],
                "refusal_conditions": [],
                "causal_claim_must_remain_unverified": False,
                "minimum_cited_sources": 1,
                "expected_codes": expected_codes,
                "expected_verdicts": {req.goal_id: metric_gold["disposition"]}
                if metric_gold
                else {},
                "retrieval_expected": "insufficient" if kind == "source_context" else "complete",
                "missing_fact_ids": ["refund_deadline"] if kind == "source_context" else [],
                "retrieval": {"relevant_document_ids": [source.document_id]},
            }
        )
    )
    context = MetricRepository(metric_data[2]).context(req)
    pins = {
        "datasets": {
            "public": {
                "schema": schema.model_dump(mode="json"),
                "semantics": {"definition_sha256": context.semantic_sha256},
                "metrics": [
                    {
                        "metric_id": req.metric_id,
                        "metric_version": req.metric_version,
                        "definition_sha256": context.metric_sha256,
                    }
                ],
            }
        },
        "corpora": {
            "public": {
                "manifest": manifest.model_dump(mode="json"),
                "index_version": pin.index_version,
            }
        },
    }
    key = secrets.token_bytes(32)
    observation = score(case, gold, sign_collection(payload, key), key, pins)
    assert observation["strict_correct"], observation
    assert observation["safety_violation"] is False
