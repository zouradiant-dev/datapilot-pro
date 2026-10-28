"""Real PG17/pgvector/MCP/durable reports; synthetic host contracts and scripted decisions."""

import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from test_cross_source_postgres import ReportDecisions
from test_rag_postgres import embedding as embedding

from datapilot.contracts import AgentFailure
from datapilot.db.management import management_url
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact
from datapilot.orchestration.runtime import ArtifactStore
from datapilot.persistence.backend import Backend, DurableArtifacts, execute
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import ChunkCitation, RagScope, Target
from datapilot.rag.mcp import rag_session
from datapilot.rag.storage import IngestionService, make_pin
from datapilot.reporting.contracts import DocumentFact, DocumentGoal, ReportScope
from datapilot.reporting.service import ReportService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("reporting_output"),
    pytest.mark.skipif(
        os.getenv("DATAPILOT_RUN_DB_TESTS") != "1",
        reason="Explicit PostgreSQL opt-in is required before any fixture/embedding setup",
    ),
]
ROOT = Path(__file__).resolve().parents[1]
OUT = None  # Bound by the module reporting_output fixture.


class Decisions(ReportDecisions):
    async def respond(self, messages, tools):
        reply = await super().respond(messages, tools)
        for call in reply.tool_calls:
            if call["name"] == "search_documents":
                call["args"]["top_k"] = 5  # Test script only; production policy is unchanged.
        return reply


class NoModel:
    async def respond(self, *_):
        raise AssertionError("Repeat resume must not issue a new model call")


@pytest.fixture(scope="module")
def fact_sources(portable_pg, embedding, tmp_path_factory):
    folder = tmp_path_factory.mktemp("document-fact-sources")
    published = folder / "bindings.json"
    texts = {
        "retention.md": (
            "# 合成访问审计规范\n\n访问审计日志必须保留七年。工作区管理员每月复核角色权限。\n"
        ),
    }
    texts["roles.md"] = (
        "# 成员角色与授权\n\n工作区管理员邀请成员并分配角色。"
        "分析员可查看报表但不能邀请成员；访客只能查看获授权的看板。"
        "调整角色后应复核访问范围。本文没有规定审计日志保留年限。\n"
    )
    texts["maintenance.md"] = (
        "# 计划维护通知\n\n计划维护安排在周日凌晨的低峰窗口。"
        "服务台提前通过站内公告和订阅邮件通知工作区管理员。"
        "紧急故障另发状态通知，计划维护窗口不是恢复时限承诺。"
        "本文没有留存率实验。\n"
    )
    paths = []
    for name, text in texts.items():
        path = folder / name
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    scope = RagScope(owner="phase3d-public-fixtures", allow_saas=True)
    service = IngestionService(management_url("rag_ingest"), embedding)
    try:
        manifest, version, reused, _ = service.ingest(
            Target(corpus_id=str(uuid4()), owner=scope.owner), paths, scope=scope, reviewed=True
        )
    finally:
        service.close()
    assert not reused
    scope.corpora = [make_pin(manifest, version)]
    binding = {"scope": scope.model_dump(mode="json"), "manifest": manifest.model_dump(mode="json")}
    with published.open("x", encoding="utf-8") as stream:
        json.dump(binding, stream, ensure_ascii=False, indent=2)
    return binding


def host_fact(binding, source_name, fact_id, quotation):
    manifest = binding["manifest"]
    source = next(s for s in manifest["sources"] if s["name"] == source_name)
    assert len(source["chunks"]) == 1
    pin = binding["scope"]["corpora"][0]
    citation = ChunkCitation(
        **source["chunks"][0],
        corpus_id=pin["corpus_id"],
        index_version=pin["index_version"],
        source_id=source["source_id"],
        document_id=source["document_id"],
        version=source["version"],
        source_sha256=source["text_sha256"],
        model_revision=manifest["model"]["revision"],
        chunker_sha256=digest(manifest["chunker"]),
        score=0.0,
    )
    return DocumentFact(
        fact_id=fact_id,
        description="Public synthetic host fixture statement",
        citation=citation,
        quotation=quotation,
        confirmation_ref="synthetic-host-contract-not-independent-human-review",
    )


def scenario(name, fresh):
    binding = fresh
    rag = RagScope.model_validate_json(json.dumps(binding["scope"]))
    question = "权限审计日志必须保留多少年？"
    purpose, facts, causal, expected = (
        "facts",
        [DocumentFact(fact_id="retention", description="Required audit retention duration")],
        False,
        "unavailable",
    )
    if name == "year":
        question = "访问审计日志必须保留多少年？"
        facts = [host_fact(binding, "retention.md", "retention", "访问审计日志必须保留七年")]
        expected = "completed"
    elif name == "absence":
        question = "这份文档是否规定了审计日志保存年限？"
        facts = [host_fact(binding, "roles.md", "policy_presence", "本文没有规定审计日志保留年限")]
        expected = "completed"
    elif name == "partial":
        question = "审计日志保存年限和管理员邀请成员的规则是什么？"
        facts.append(
            host_fact(binding, "roles.md", "member_role", "工作区管理员邀请成员并分配角色")
        )
        expected = "partial"
    elif name == "summary":
        question = "总结访问审计日志保存和管理员权限复核的文档规定。"
        purpose, facts, expected = "summary", [], "completed"
    elif name == "causal":
        question = "维护窗口安排是否已经由随机实验证明能提高客户留存？"
        purpose, facts, causal, expected = "conclusion", [], True, "partial"
    scope = ReportScope(
        owner=rag.owner,
        question=question,
        datasets=rag.datasets,
        metrics=[],
        document_goal=DocumentGoal(
            goal_id="documents",
            question=question,
            metric_goals=[],
            purpose=purpose,
            required_facts=facts,
        ),
        causal_requested=causal,
    )
    return rag, scope, expected


@pytest.mark.parametrize("name", ["missing", "year", "absence", "partial", "summary", "causal"])
def test_real_worker_receipt_report_and_persistent_fact_coverage(pg_settings, fact_sources, name):
    rag, scope, expected = scenario(name, fact_sources)
    run_id = str(uuid4())
    result = run_async(
        run_durable(
            pg_settings,
            run_id,
            scope.question,
            owner=scope.owner,
            report_scope=scope,
            rag_scope=rag,
            transport=Decisions(scope.question),
        )
    )
    report = result["cross_source_report"]
    # Retrieval can complete while the requested fact/conclusion remains unverified.
    receipt = result["results"]["1:documents"].rag_completion
    assert (
        receipt.submission.outcome == "complete" and receipt.business_conclusions_verified is False
    )
    assert report.business_completion.status == expected and not report.charts
    backend = Backend(pg_settings.runtime_database_url.get_secret_value(), run_id, scope.owner)
    try:
        artifacts = DurableArtifacts(backend).export()
        with backend.transaction() as conn:
            calls = [
                dict(r)
                for r in execute(
                    conn,
                    "SELECT call_key,status,payload_hash FROM execution.calls "
                    "WHERE run_id=:r ORDER BY call_key",
                    r=run_id,
                ).mappings()
            ]
        assert all(r["status"] == "complete" for r in calls)
        repeated = run_async(
            run_durable(
                pg_settings,
                run_id,
                resume=True,
                owner=scope.owner,
                report_scope=scope,
                rag_scope=rag,
                transport=NoModel(),
            )
        )
        assert result["usage"] == repeated["usage"] and report == repeated["cross_source_report"]
        assert artifacts == DurableArtifacts(backend).export()
        with backend.transaction() as conn:
            assert calls == [
                dict(r)
                for r in execute(
                    conn,
                    "SELECT call_key,status,payload_hash FROM execution.calls "
                    "WHERE run_id=:r ORDER BY call_key",
                    r=run_id,
                ).mappings()
            ]
    finally:
        backend.close()
    if name in {"missing", "partial"}:
        assert (
            "document_fact_unverified:retention"
            in report.business_completion.missing_evidence["documents"]
        )
        assert "documents" not in report.business_completion.verified_goals
    if name == "causal":
        assert report.business_completion.unconfirmed_claims == ["causal_conclusion_not_verified"]
    with (OUT / f"{sys.version_info.minor}-{name}-{run_id}.json").open(
        "x", encoding="utf-8"
    ) as stream:
        json.dump(
            {
                "run_id": run_id,
                "report": report.model_dump(mode="json"),
                "usage": result["usage"],
                "receipt": receipt.model_dump(mode="json"),
                "calls": calls,
            },
            stream,
            ensure_ascii=False,
            indent=2,
        )


def test_real_pins_and_scope_cannot_be_forged(pg_settings, fact_sources):
    rag, scope, _ = scenario("year", fact_sources)

    async def check():
        async with rag_session(pg_settings, rag, goal=scope.question) as tools:
            result = await tools.search(scope.question, 5)
            assert result.documents
            service = ReportService(pg_settings, scope, {}, {}, {}, {})
            for field in ("sha256", "version", "index_version", "source_sha256"):
                corrupt = result.model_copy(deep=True)
                setattr(corrupt.documents[0].citation, field, "0" * 64)
                store = ArtifactStore("corrupt-source")
                ref = store.put(
                    Artifact(
                        run_id=store.run_id,
                        task_id="documents",
                        plan_version=1,
                        kind="documents",
                        source="real-rag-adversarial-copy",
                        documents=corrupt,
                    )
                )
                with pytest.raises(AgentFailure):
                    service.build([(ref, store.get(ref))], tools)

    run_async(check())
    rag.owner = "not-the-owner"

    async def deny():
        async with rag_session(pg_settings, rag, goal=scope.question):
            pytest.fail("Scope was expanded")

    with pytest.raises(AgentFailure) as exc:
        run_async(deny())
    assert exc.value.error.code == "DOCUMENT_NOT_AUTHORIZED"
