"""Fresh safety fixtures through original PG/MCP/Durable, with scripted decisions."""

import json
import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from reporting_fixtures import host_scope, metric_fixture
from test_host_goal_postgres import probe
from test_partial_evidence_postgres import snapshot
from test_qwen_migration_postgres import ingest_public

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetScope
from datapilot.orchestration.runtime import text_hash
from datapilot.persistence.inspection import inspect_run
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import RagScope, Target
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService, make_pin
from datapilot.reporting.contracts import CitationPolicy, CitationSource

DATA = json.loads(
    (Path(__file__).parent / "fixtures/rag/host-goal-requirements-v3.json").read_bytes()
)["e2e"]
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", params=["bge", "qwen"])
def goal_dev(request, portable_pg, tmp_path_factory):
    if request.param == "qwen" and os.getenv("DATAPILOT_RUN_QWEN_TESTS") != "1":
        pytest.skip("Explicit real Qwen CUDA opt-in required")
    folder = tmp_path_factory.mktemp("goal-v3-" + request.param)
    assets = folder / "assets"
    sources = dict(DATA["sources"])
    sources["export-policy.md"] += " 本期已支付账单收入是独立财务指标。"
    if request.param == "qwen":
        scope, manifest = ingest_public(portable_pg, assets, sources, "qwen3-cuda-fp16-v1")
    else:
        assets.mkdir()
        for name, text in sources.items():
            (assets / name).write_text(text, encoding="utf-8")
        scope = RagScope(allow_saas=True)
        service = IngestionService(
            os.environ["DATAPILOT_RAG_INGEST_DATABASE_URL"], LocalEmbedding()
        )
        try:
            manifest, index, _, _ = service.ingest(
                Target(corpus_id=str(uuid4())),
                sorted(assets.glob("*.md")),
                scope=scope,
                reviewed=True,
            )
        finally:
            service.close()
        scope.corpora = [make_pin(manifest, index)]
    binding = {
        "scope": scope.model_dump(mode="json"),
        "manifest": manifest.model_dump(mode="json"),
        "metric": None,
    }
    (folder / "binding.json").write_text(json.dumps(binding), encoding="utf-8")
    with pytest.MonkeyPatch.context() as patch:
        for key, value in portable_pg.model_dump().items():
            if isinstance(value, (str, bool, int, float)):
                patch.setenv("DATAPILOT_" + key.upper(), str(value))
        yield portable_pg, folder, request.param, sources, binding


def configured(dev, kind):
    _, _, _, sources, binding = dev
    question = DATA.get(kind + "_query", DATA["query"])
    facts = [["export_approval", "export-policy.md", DATA["quote"]]]
    if kind == "missing":
        facts = [["unknown_retention", None, None]]
    if kind == "partial":
        facts.append(["unknown_retention", None, None])
    if kind == "causal":
        question = "沙盒导出审批需要哪些角色确认，能否证明因此提升收入？"
    if kind == "content":
        question = "遍历所有内容，核对沙盒导出审批。"
    rag, report = host_scope(
        {"id": "public-v3-" + kind, "question": question, "documents": sources, "facts": facts},
        binding,
    )
    report.partial_evidence_policy = "partial-facts-v1"
    report.rag_query_policy = "original-first-v1"
    report.causal_requested = kind == "causal"
    required = [
        CitationSource(
            corpus_id=rag.corpora[0].corpus_id,
            index_version=rag.corpora[0].index_version,
            source_id=s["source_id"],
            document_id=s["document_id"],
            version=s["version"],
            source_sha256=s["text_sha256"],
        )
        for s in binding["manifest"]["sources"]
        if s["name"] == "export-policy.md" or kind == "required_gap"
    ]
    report.citation_policy = CitationPolicy(
        goal_sha256=text_hash(question), required_sources=required
    )
    return rag, report


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("complete", "completed"),
        ("negative", "completed"),
        ("partial", "partial"),
        ("missing", "unavailable"),
        ("exhaustive", "unavailable"),
        ("double", "unavailable"),
        ("ambiguous", "unavailable"),
        ("required_gap", "partial"),
        ("causal", "partial"),
        ("content", "unavailable"),
    ],
)
def test_goal_and_business_eligibility_remain_separate(goal_dev, kind, expected):
    settings, folder, _, _, _ = goal_dev
    rag, report = configured(goal_dev, kind)
    id_ = str(uuid4())
    result = probe(goal_dev, "start", id_, rag, report)
    (folder / (id_ + "-result.json")).write_text(json.dumps(result), encoding="utf-8")
    assert result["business_completion"]["status"] == expected
    assert all(c["metric"] is None for c in result["cross_source_report"]["claims"])
    if kind in {"exhaustive", "double", "ambiguous", "content"}:
        task = result["results"]["1:documents"]
        assert task["rag_completion"]["submission"]["outcome"] != "complete"
        assert not result["business_completion"]["verified_goals"]
    inspected = run_async(
        inspect_run(
            settings, id_, report.owner, report.question, report_scope=report, rag_scope=rag
        )
    )
    assert not inspected["unknown"] and inspected["report"]


@pytest.mark.parametrize("fault", ["owner", "version", "profile"])
def test_text_cannot_grant_owner_version_or_model_scope(goal_dev, fault):
    settings, _, _, _, _ = goal_dev
    rag, report = configured(goal_dev, "complete")
    if fault == "owner":
        rag.owner = "other-owner"
    elif fault == "version":
        rag.corpora[0].index_version = "0" * 64
    else:
        rag.embedding_profile = "qwen3-cpu-v1" if rag.embedding_profile else "qwen3-cuda-fp16-v1"
    with pytest.raises(AgentFailure):
        run_async(
            run_durable(settings, str(uuid4()), report.question, rag_scope=rag, report_scope=report)
        )


@pytest.mark.parametrize("legacy", [False, True])
def test_cross_process_v3_reuse_or_v2_identity_rejection(goal_dev, legacy):
    settings, _, _, _, _ = goal_dev
    rag, report = configured(goal_dev, "complete")
    id_ = str(uuid4())
    paused = probe(goal_dev, "start", id_, rag, report, "--pause", *(["--v2"] if legacy else []))
    assert paused["status"] == "paused"
    before = snapshot(settings, id_, report.owner)
    if legacy:
        denied = probe(goal_dev, "resume", id_, rag, report, expected=2)
        assert denied["error"]["code"] == "RECOVERY_IDENTITY"
    else:
        resumed = probe(goal_dev, "resume", id_, rag, report)
        assert resumed["business_completion"]["status"] == "completed"
        before = snapshot(settings, id_, report.owner)
        repeated = probe(goal_dev, "resume", id_, rag, report)
        assert repeated["cross_source_report"] == resumed["cross_source_report"]
        assert repeated["usage"] == resumed["usage"]
    assert before == snapshot(settings, id_, report.owner)


def test_unknown_tool_outcome_never_reissued(goal_dev):
    settings, _, _, _, _ = goal_dev
    rag, report = configured(goal_dev, "complete")
    id_ = str(uuid4())
    probe(goal_dev, "start", id_, rag, report, "--cut", "tool_issued", expected=91)
    before = snapshot(settings, id_, report.owner)
    denied = probe(goal_dev, "resume", id_, rag, report, expected=2)
    assert denied["error"]["code"] == "RECOVERY_UNCERTAIN"
    after = snapshot(settings, id_, report.owner)
    assert before["ledger"] == after["ledger"]
    assert before["artifacts"] == after["artifacts"]
    assert [(c["call_key"], c["payload_hash"]) for c in before["calls"]] == [
        (c["call_key"], c["payload_hash"]) for c in after["calls"]
    ]


def test_numeric_claims_keep_original_p3_proof(goal_dev):
    settings, folder, _, _, _ = goal_dev
    mfolder = folder / "metric"
    mfolder.mkdir()
    metric = metric_fixture(os.environ, mfolder, "public-goal-v3-" + uuid4().hex)
    rag, report = configured(goal_dev, "complete")
    from datapilot.semantics.contracts import MetricRequest

    request = MetricRequest.model_validate_json(json.dumps(metric["request"]))
    rag.datasets = report.datasets = DatasetScope.model_validate_json(json.dumps(metric["scope"]))
    report.metrics = [request]
    report.document_goal.metric_goals = [request.goal_id]
    report.question = report.document_goal.question = (
        "分析已支付账单收入，结合沙盒导出审批角色规则给出背景。"
    )
    report.citation_policy.goal_sha256 = text_hash(report.question)
    id_ = str(uuid4())
    result = probe(goal_dev, "start", id_, rag, report)
    claims = result["cross_source_report"]["claims"]
    bridge = next(c["metric"] for c in claims if c["kind"] == "metric")
    assert bridge["verdict"] == bridge["verification"]["verdict"] == "verified"
    assert Decimal(bridge["value"]["value"]) == Decimal(metric["gold_decimal"])
    assert bridge["value"]["unit"] == "CNY"
    inspected = run_async(
        inspect_run(
            settings, id_, report.owner, report.question, report_scope=report, rag_scope=rag
        )
    )
    assert not inspected["unknown"] and inspected["report"]


def test_report_independently_denies_exhaustiveness_despite_real_qualified_facts(goal_dev):
    from datapilot.orchestration.contracts import Artifact
    from datapilot.orchestration.rag_completion import retrieval_goal
    from datapilot.orchestration.runtime import ArtifactStore
    from datapilot.rag.mcp import rag_session
    from datapilot.reporting.service import report_session

    settings, _, _, _, _ = goal_dev
    rag, report = configured(goal_dev, "complete")
    question = "沙盒导出审批需要哪些角色确认？核对全部来源，确保无遗漏。"
    report.question = report.document_goal.question = question
    report.citation_policy.goal_sha256 = text_hash(question)

    async def check():
        async with (
            rag_session(settings, rag, goal=question) as retrieval,
            report_session(settings, report, question, report.owner) as service,
        ):
            found = await retrieval.search(DATA["query"], 3)
            goal = retrieval_goal(question, retrieval)
            assert goal["unsupported_requirements"]
            # Prove this is not a refusal due to empty retrieval, unrelated text or bad hashes.
            retrieval.validate_result(found)
            assert any(
                DATA["quote"] in d.text
                for d in retrieval.qualifying_documents(found.documents, goal)
            )
            store = ArtifactStore("public-v3-report-boundary")
            ref = store.put(
                Artifact(
                    run_id=store.run_id,
                    task_id="documents",
                    plan_version=1,
                    kind="documents",
                    source="real-authorized-mcp-test",
                    documents=found,
                )
            )
            result = service.build(
                [(ref, store.get(ref))], retrieval, source_statuses={"documents": "succeeded"}
            )
            assert result.business_completion.status == "unavailable"
            assert not result.business_completion.verified_goals
            assert all(not c.documents for c in result.claims)

    run_async(check())
