"""New PG/MCP/BGE/Qwen safety contracts; scripted decisions, no paid model."""

import json
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from reporting_fixtures import host_scope, metric_fixture
from test_cross_source_postgres import ReportDecisions
from test_host_goal_postgres import probe
from test_partial_evidence_postgres import snapshot
from test_qwen_migration_postgres import ingest_public

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetScope
from datapilot.orchestration.contracts import Artifact
from datapilot.orchestration.runtime import ArtifactStore, text_hash
from datapilot.persistence.inspection import inspect_run
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import RagScope, Target
from datapilot.rag.mcp import rag_session
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService, make_pin
from datapilot.reporting.contracts import CitationPolicy, CitationSource, confirm_finite_scope
from datapilot.reporting.service import report_session

pytestmark = pytest.mark.integration
QUESTION = "根据指定规则，说明租户归档由谁审批以及导出链接多久失效。"
QUOTE = "租户归档由租户管理员审批，导出链接两小时后失效"
SOURCES = {
    "archive-handover.md": "公开合成租户归档规则："
    + QUOTE
    + "。已支付账单收入不受本文背景说明改变。",
    "calendar-color.md": "公开合成日历显示说明：节假日显示浅蓝色，颜色不涉及租户归档和导出授权。",
}


@pytest.fixture(scope="module", params=["bge", "qwen"])
def scope_dev(request, portable_pg, tmp_path_factory):
    if request.param == "qwen" and os.getenv("DATAPILOT_RUN_QWEN_TESTS") != "1":
        pytest.skip("Explicit real CUDA test opt-in required")
    folder = tmp_path_factory.mktemp("scope-v4-" + request.param)
    assets = folder / "assets"
    if request.param == "qwen":
        rag, manifest = ingest_public(portable_pg, assets, SOURCES, "qwen3-cuda-fp16-v1")
    else:
        assets.mkdir()
        for name, text in SOURCES.items():
            (assets / name).write_text(text, encoding="utf-8")
        rag = RagScope(allow_saas=True)
        service = IngestionService(
            os.environ["DATAPILOT_RAG_INGEST_DATABASE_URL"], LocalEmbedding()
        )
        try:
            manifest, index, _, _ = service.ingest(
                Target(corpus_id=str(uuid4())),
                sorted(assets.glob("*.md")),
                scope=rag,
                reviewed=True,
            )
        finally:
            service.close()
        rag.corpora = [make_pin(manifest, index)]
    binding = {
        "scope": rag.model_dump(mode="json"),
        "manifest": manifest.model_dump(mode="json"),
        "metric": None,
    }
    (folder / "binding.json").write_text(json.dumps(binding), encoding="utf-8")
    with pytest.MonkeyPatch.context() as patch:
        for key, value in portable_pg.model_dump().items():
            if isinstance(value, (str, bool, int, float)):
                patch.setenv("DATAPILOT_" + key.upper(), str(value))
        yield portable_pg, folder, request.param, SOURCES, binding


def configured(dev, kind="complete"):
    *_, binding = dev
    question = {
        "unknown": "这次归档的审核材料边界仍待商定，请先解决范围，再判断交接是否齐备。",
        "exhaustive": "逐篇检查所有文档，不能遗漏任一来源。",
        "negative": "无需检查全部文档，只说明已确认的租户归档审批事实。",
    }.get(kind, QUESTION)
    facts = [["archive_rule", "archive-handover.md", QUOTE]]
    if kind == "partial":
        facts.append(["unknown_schedule", None, None])
    rag, scope = host_scope(
        {
            "id": "public-scope-v4-" + kind,
            "question": question,
            "facts": facts,
            "documents": SOURCES,
        },
        binding,
    )
    scope.partial_evidence_policy, scope.rag_query_policy = "partial-facts-v1", "original-first-v1"
    source = next(s for s in binding["manifest"]["sources"] if s["name"] == "archive-handover.md")
    scope.citation_policy = CitationPolicy(
        goal_sha256=text_hash(question),
        required_sources=[
            CitationSource(
                corpus_id=rag.corpora[0].corpus_id,
                index_version=rag.corpora[0].index_version,
                source_id=source["source_id"],
                document_id=source["document_id"],
                version=source["version"],
                source_sha256=source["text_sha256"],
            )
        ],
    )
    if kind not in {"unknown", "exhaustive"}:
        scope = confirm_finite_scope(
            scope, rag, confirmation_ref="public-host-reviewed-finite-scope-v4"
        )
    return rag, scope


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("complete", "completed"),
        ("negative", "completed"),
        ("partial", "partial"),
        ("unknown", "unavailable"),
        ("exhaustive", "unavailable"),
    ],
)
def test_real_scoped_completion(scope_dev, kind, expected):
    settings, folder, *_ = scope_dev
    rag, scope = configured(scope_dev, kind)
    id_ = str(uuid4())
    result = probe(scope_dev, "start", id_, rag, scope)
    (folder / (id_ + "-result.json")).write_text(json.dumps(result), encoding="utf-8")
    completion = result["business_completion"]
    assert completion["status"] == expected
    receipt = result["results"]["1:documents"]["rag_completion"]
    if kind in {"unknown", "exhaustive"}:
        # Actual empty retrieval must use unavailable, nonempty uses insufficient.
        assert receipt["submission"]["outcome"] in {"insufficient", "unavailable"}
    else:
        assert receipt["submission"]["outcome"] == "complete"
    if kind == "unknown":
        assert "goal_scope_not_attested" in completion["missing_evidence"]["documents"]
    inspected = run_async(
        inspect_run(settings, id_, scope.owner, scope.question, report_scope=scope, rag_scope=rag)
    )
    assert not inspected["unknown"] and inspected["report"]


@pytest.mark.parametrize("fault", ["owner", "version", "profile"])
def test_no_confirmation_grants_authority(scope_dev, fault):
    settings, *_ = scope_dev
    rag, scope = configured(scope_dev)
    if fault == "owner":
        rag.owner = "unapproved-owner"
    elif fault == "version":
        rag.corpora[0].index_version = "0" * 64
    else:
        rag.embedding_profile = "qwen3-cpu-v1" if rag.embedding_profile else "qwen3-cuda-fp16-v1"
    with pytest.raises(AgentFailure):
        run_async(
            run_durable(settings, str(uuid4()), scope.question, rag_scope=rag, report_scope=scope)
        )


@pytest.mark.parametrize("old_v3", [False, True])
def test_cross_process_attestation_or_v3_identity_refusal(scope_dev, old_v3):
    settings, *_ = scope_dev
    rag, scope = configured(scope_dev)
    if old_v3:
        scope.goal_scope_attestation = None
    id_ = str(uuid4())
    paused = probe(scope_dev, "start", id_, rag, scope, "--pause", *(["--v3"] if old_v3 else []))
    assert paused["status"] == "paused"
    before = snapshot(settings, id_, scope.owner)
    if old_v3:
        refused = probe(scope_dev, "resume", id_, rag, scope, expected=2)
        assert refused["error"]["code"] == "RECOVERY_IDENTITY"
    else:
        resumed = probe(scope_dev, "resume", id_, rag, scope)
        assert resumed["business_completion"]["status"] == "completed"
        before = snapshot(settings, id_, scope.owner)
        again = probe(scope_dev, "resume", id_, rag, scope)
        assert again["cross_source_report"] == resumed["cross_source_report"]
        assert again["usage"] == resumed["usage"]
    assert before == snapshot(settings, id_, scope.owner)


def test_unknown_tool_never_reissued(scope_dev):
    settings, *_ = scope_dev
    rag, scope = configured(scope_dev)
    id_ = str(uuid4())
    probe(scope_dev, "start", id_, rag, scope, "--cut", "tool_issued", expected=91)
    before = snapshot(settings, id_, scope.owner)
    refused = probe(scope_dev, "resume", id_, rag, scope, expected=2)
    assert refused["error"]["code"] == "RECOVERY_UNCERTAIN"
    after = snapshot(settings, id_, scope.owner)
    assert before["artifacts"] == after["artifacts"] and before["ledger"] == after["ledger"]
    assert [(r["call_key"], r["payload_hash"]) for r in before["calls"]] == [
        (r["call_key"], r["payload_hash"]) for r in after["calls"]
    ]


def test_report_rechecks_real_source_against_unknown_scope(scope_dev):
    settings, *_ = scope_dev
    rag, scope = configured(scope_dev, "unknown")

    async def check():
        async with (
            rag_session(settings, rag, goal=scope.document_goal.question) as retrieval,
            report_session(settings, scope, scope.question, scope.owner) as reporting,
        ):
            found = await retrieval.search(QUESTION, 3)
            retrieval.validate_result(found)
            assert any(QUOTE in d.text for d in found.documents)
            store = ArtifactStore("scope-v4-independent-report")
            ref = store.put(
                Artifact(
                    run_id=store.run_id,
                    task_id="documents",
                    plan_version=1,
                    kind="documents",
                    source="real-mcp",
                    documents=found,
                )
            )
            built = reporting.build(
                [(ref, store.get(ref))], retrieval, source_statuses={"documents": "succeeded"}
            )
            assert built.business_completion.status == "unavailable"
            assert (
                "goal_scope_not_attested" in built.business_completion.missing_evidence["documents"]
            )

    run_async(check())


def test_verified_p3_does_not_cover_unconfirmed_document_scope(scope_dev):
    from datapilot.semantics.contracts import MetricRequest

    settings, folder, *_ = scope_dev
    d = folder / ("metric-" + uuid4().hex)
    d.mkdir()
    metric = metric_fixture(os.environ, d, "public-v4-" + uuid4().hex[:12])
    rag, scope = configured(scope_dev, "unknown")
    scope.datasets = rag.datasets = DatasetScope.model_validate_json(json.dumps(metric["scope"]))
    scope.metrics = [MetricRequest.model_validate_json(json.dumps(metric["request"]))]
    scope.document_goal.metric_goals = [scope.metrics[0].goal_id]
    # A real P3 number remains visible; the unresolved other goal keeps the whole task partial.
    id_ = str(uuid4())
    result = probe(scope_dev, "start", id_, rag, scope)
    claims = result["cross_source_report"]["claims"]
    bridge = next(c["metric"] for c in claims if c["kind"] == "metric")
    assert bridge["verdict"] == bridge["verification"]["verdict"] == "verified"
    assert Decimal(bridge["value"]["value"]) == Decimal(metric["gold_decimal"])
    assert bridge["value"]["unit"] == "CNY"
    assert result["business_completion"]["status"] == "partial"
    assert (
        "goal_scope_not_attested" in result["business_completion"]["missing_evidence"]["documents"]
    )
    before = snapshot(settings, id_, scope.owner)
    inspected = run_async(
        inspect_run(settings, id_, scope.owner, scope.question, report_scope=scope, rag_scope=rag)
    )
    assert inspected["report"] and not inspected["unknown"]
    assert before == snapshot(settings, id_, scope.owner)
    sql = scope.model_copy(deep=True)
    sql.document_goal = None
    sql.citation_policy = None
    sql.rag_query_policy = "legacy"
    sql.question = "查询已确认窗口内的已支付账单收入。"
    isolated = run_async(
        run_durable(
            settings, str(uuid4()), sql.question, report_scope=sql, transport=ReportDecisions("")
        )
    )
    assert isolated["business_completion"].status == "completed"
