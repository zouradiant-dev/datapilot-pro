"""Opt-in real Qwen/PG/MCP/Report/Durable. Model decisions are explicitly scripted."""

import asyncio
import hashlib
import json
import os
import subprocess
import time
from functools import partial
from pathlib import Path
from uuid import uuid4

import pytest
from test_cross_source_postgres import ReportDecisions, probe

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetScope
from datapilot.ingestion.common import digest
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import ChunkCitation, IndexManifest, RagScope
from datapilot.rag.mcp import MCPRetrievalTools, rag_session
from datapilot.rag.qwen import interpreter, policy
from datapilot.rag.storage import Repository, validate_manifest_profile
from datapilot.reporting.contracts import (
    CitationPolicy,
    CitationSource,
    DocumentFact,
    DocumentGoal,
    ReportScope,
)
from datapilot.runtime.mcp_client import server_environment

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]
QUESTION = "How does maintenance freeze affect new and running workflows?"


def ingest_public(settings, folder, sources, profile=None):
    profile = profile or os.getenv("DATAPILOT_QWEN_TEST_PROFILE", "qwen3-cuda-fp16-v1")
    assert profile in {"qwen3-cpu-v1", "qwen3-cuda-fp16-v1"}
    folder.mkdir(parents=True)
    paths = []
    for name, text in sources.items():
        path = folder / name
        path.write_text(text, encoding="utf-8")
        paths.extend(["--file", str(path)])
    env = server_environment(settings)
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        DATAPILOT_API_KEY="",
        DATAPILOT_RAG_INGEST_DATABASE_URL=os.environ["DATAPILOT_RAG_INGEST_DATABASE_URL"],
    )
    scope_path = folder / "scope.json"
    result = subprocess.run(
        [
            interpreter(),
            "-m",
            "datapilot.cli",
            "rag",
            "ingest",
            "--corpus",
            str(uuid4()),
            *paths,
            "--saas",
            "--reviewed",
            "--embedding-profile",
            profile,
            "--output",
            str(scope_path),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-800:]
    scope = RagScope.model_validate_json(scope_path.read_bytes())
    repo = Repository(settings.rag_reader_database_url.get_secret_value(), scope)
    try:
        manifest = next(iter(repo.manifests().values()))
    finally:
        repo.close()
    return scope, manifest


@pytest.fixture(scope="module")
def qwen_dev(portable_pg):
    if os.getenv("DATAPILOT_RUN_QWEN_TESTS") != "1":
        pytest.skip("Explicit local Qwen integration opt-in required; never substitutes vectors")
    folder = ROOT / "artifacts/tests" / ("qwen-" + uuid4().hex)
    data = json.loads((ROOT / "tests/fixtures/rag/qwen-migration-dev.json").read_bytes())
    scope, manifest = ingest_public(portable_pg, folder, data["splits"]["validation"]["sources"])
    # The existing recovery CLI reads .env; explicitly bind every scalar host policy
    # so a developer's unrelated model settings cannot silently change its manifest.
    with pytest.MonkeyPatch.context() as patch:
        for key, value in portable_pg.model_dump().items():
            if isinstance(value, (str, bool, int, float)):
                patch.setenv("DATAPILOT_" + key.upper(), str(value))
        yield portable_pg, folder, scope, manifest


def report_scope(scope, manifest, *, kind="complete"):
    question = "谁检查共享会议室日历？" if kind == "injection" else QUESTION
    name = "injection-zh.md" if kind == "injection" else "freeze-en.md"
    source = next(s for s in manifest.sources if s.name == name)
    span = source.chunks[0]
    text = json.loads((ROOT / "tests/fixtures/rag/qwen-migration-dev.json").read_bytes())["splits"][
        "validation"
    ]["sources"][name]
    citation = ChunkCitation(
        **span.model_dump(),
        corpus_id=manifest.target.corpus_id,
        index_version=scope.corpora[0].index_version,
        source_id=source.source_id,
        document_id=source.document_id,
        version=source.version,
        source_sha256=source.version,
        model_revision=manifest.model.revision,
        chunker_sha256=digest(manifest.chunker),
        score=1,
    )
    proof = DocumentFact(
        fact_id="rule",
        description="Public Dev operational rule",
        citation=citation,
        quotation=text[span.start : span.end],
        confirmation_ref="public-dev-1",
    )
    missing = DocumentFact(fact_id="not_in_source", description="An unattested business fact")
    facts = [missing] if kind == "missing" else [proof, missing] if kind == "partial" else [proof]
    return ReportScope(
        question=question,
        datasets=DatasetScope(),
        metrics=[],
        document_goal=DocumentGoal(
            goal_id="documents",
            question=question,
            metric_goals=[],
            purpose="facts",
            required_facts=facts,
        ),
        causal_requested=kind == "causal",
        partial_evidence_policy="partial-facts-v1",
        rag_query_policy="original-first-v1",
        citation_policy=CitationPolicy(
            goal_sha256=hashlib.sha256(question.encode()).hexdigest(),
            required_sources=[
                CitationSource(**citation.model_dump(include=set(CitationSource.model_fields)))
            ],
        ),
    )


@pytest.mark.parametrize("kind", ["owner", "version", "model", "precision"])
def test_real_preflight_refuses_scope_index_or_recipe_mixing(qwen_dev, kind):
    settings, _, scope, manifest = qwen_dev
    bad = scope.model_copy(deep=True)
    if kind == "owner":
        bad.owner = "other-owner"
    elif kind == "version":
        bad.corpora[0].index_version = "0" * 64
    elif kind == "model":
        bad.embedding_profile = None
    else:
        bad.embedding_profile = (
            "qwen3-cpu-v1" if scope.embedding_profile != "qwen3-cpu-v1" else "qwen3-cuda-fp16-v1"
        )

    async def check():
        async with rag_session(settings, bad):
            pytest.fail("Cross-model/owner/version grant accepted")

    with pytest.raises(AgentFailure):
        run_async(check())
    altered = IndexManifest.model_validate_json(manifest.model_dump_json())
    altered.relevance_policy_sha256 = "0" * 64
    with pytest.raises(AgentFailure):
        validate_manifest_profile(altered, scope)


def test_real_goal_binding_and_citation_integrity(qwen_dev):
    settings, _, scope, _ = qwen_dev

    async def check():
        from datapilot.orchestration.rag_completion import retrieval_goal

        async with rag_session(settings, scope, goal=QUESTION) as tools:
            result = await tools.search(QUESTION, 3)
            goal = retrieval_goal(QUESTION, tools)
            assert goal["relevance_policy"] == policy(scope.embedding_profile)["goal_policy"]
            assert tools.qualifying_documents(result.documents, goal)
            assert not tools.qualifying_documents(
                result.documents, retrieval_goal("Another goal", tools)
            )
            for mutation in ["index_version", "model_revision", "source_sha256", "goal_sha256"]:
                bad = result.model_copy(deep=True)
                setattr(
                    bad.documents[0].citation,
                    mutation,
                    "0" * (40 if mutation == "model_revision" else 64),
                )
                with pytest.raises(AgentFailure):
                    tools.validate_result(bad)

    run_async(check())


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("complete", "completed"),
        ("partial", "partial"),
        ("missing", "unavailable"),
        ("causal", "partial"),
        ("injection", "unavailable"),
    ],
)
def test_real_rag_fact_and_business_completion_remain_separate(qwen_dev, kind, expected):
    settings, _, scope, manifest = qwen_dev
    report = report_scope(scope, manifest, kind=kind)
    result = run_async(
        run_durable(
            settings,
            str(uuid4()),
            report.question,
            rag_scope=scope,
            report_scope=report,
            transport=ReportDecisions(report.question),
        )
    )
    assert result["business_completion"].status == expected
    assert not result["cross_source_report"].charts
    assert all(c.metric is None for c in result["cross_source_report"].claims)
    assert all(
        not t.rag_completion.business_conclusions_verified
        for t in result["results"].values()
        if t.rag_completion
    )
    if kind == "causal":
        assert "causal_conclusion_not_verified" in result["business_completion"].unconfirmed_claims


def test_real_cross_process_replay_and_policy_drift_refusal(qwen_dev):
    settings, folder, scope, manifest = qwen_dev
    report = report_scope(scope, manifest)
    rpath, spath = folder / "report.json", folder / "scope.json"
    rpath.write_text(report.model_dump_json(), encoding="utf-8")
    run_id = str(uuid4())
    first = run_async(
        run_durable(
            settings,
            run_id,
            report.question,
            rag_scope=scope,
            report_scope=report,
            transport=ReportDecisions(report.question),
            interrupt_after=["worker"],
        )
    )
    assert first["status"] == "paused"
    bad = scope.model_copy(
        update={
            "embedding_profile": (
                "qwen3-cpu-v1"
                if scope.embedding_profile != "qwen3-cpu-v1"
                else "qwen3-cuda-fp16-v1"
            )
        }
    )
    with pytest.raises(AgentFailure):
        run_async(run_durable(settings, run_id, resume=True, rag_scope=bad, report_scope=report))
    resumed = probe("resume", run_id, rpath, "--rag-scope", str(spath))
    repeated = probe("resume", run_id, rpath, "--rag-scope", str(spath))
    assert resumed["business_completion"]["status"] == "completed"
    assert resumed["usage"] == repeated["usage"]
    assert resumed["cross_source_report"] == repeated["cross_source_report"]


def test_high_similarity_distractors_cannot_replace_missing_required_source(qwen_dev):
    settings, parent, _, _ = qwen_dev
    data = json.loads((ROOT / "tests/fixtures/rag/qwen-migration-safety.json").read_bytes())
    folder = parent / "hard-negatives"
    scope, manifest = ingest_public(settings, folder, data["sources"])
    name, question = data["required_source"], data["question"]
    source = next(s for s in manifest.sources if s.name == name)
    span = source.chunks[0]
    citation = ChunkCitation(
        **span.model_dump(),
        corpus_id=manifest.target.corpus_id,
        index_version=scope.corpora[0].index_version,
        source_id=source.source_id,
        document_id=source.document_id,
        version=source.version,
        source_sha256=source.version,
        model_revision=manifest.model.revision,
        chunker_sha256=digest(manifest.chunker),
        score=1,
    )
    fact = DocumentFact(
        fact_id="freeze_rule",
        description=data["gold"]["valid_fact"],
        citation=citation,
        quotation=data["sources"][name],
        confirmation_ref="public-safety-dev-1",
    )
    report = ReportScope(
        question=question,
        datasets=DatasetScope(),
        metrics=[],
        document_goal=DocumentGoal(
            goal_id="documents",
            question=question,
            metric_goals=[],
            purpose="facts",
            required_facts=[fact],
        ),
        partial_evidence_policy="partial-facts-v1",
        rag_query_policy="original-first-v1",
        citation_policy=CitationPolicy(
            goal_sha256=hashlib.sha256(question.encode()).hexdigest(),
            required_sources=[
                CitationSource(**citation.model_dump(include=set(CitationSource.model_fields)))
            ],
        ),
    )

    async def check():
        async with rag_session(settings, scope, goal=question) as retrieval:
            return await retrieval.search(question, 3)

    found = run_async(check())
    result = run_async(
        run_durable(
            settings,
            str(uuid4()),
            question,
            rag_scope=scope,
            report_scope=report,
            transport=ReportDecisions(question),
        )
    )
    published = result["cross_source_report"]
    published_refs = [d for claim in published.claims for d in claim.documents]
    assert all(c.citation.document_id == source.document_id for c in published_refs)
    if result["business_completion"].status == "completed":
        assert published_refs and any(
            c.fact_coverage.get("freeze_rule") is not None for c in published.claims
        )
    # Both Required pins must be satisfied, even when an authentic distractor is retrieved.
    other = next(s for s in manifest.sources if s.name == "withdrawn-en.md")
    required = report.model_copy(deep=True)
    required.citation_policy.required_sources.append(
        CitationSource(
            corpus_id=manifest.target.corpus_id,
            index_version=scope.corpora[0].index_version,
            source_id=other.source_id,
            document_id=other.document_id,
            version=other.version,
            source_sha256=other.version,
        )
    )
    # No reviewed fact binds the withdrawn source; it cannot fill a Required gap.
    guarded = run_async(
        run_durable(
            settings,
            str(uuid4()),
            question,
            rag_scope=scope,
            report_scope=required,
            transport=ReportDecisions(question),
        )
    )
    assert guarded["business_completion"].status != "completed"
    (folder / "result.json").write_text(
        json.dumps(
            {
                "scores": {d.source: d.citation.score for d in found.documents},
                "business_completion": result["business_completion"].status,
                "extra_required_completion": guarded["business_completion"].status,
                "published_source_ids": [c.citation.source_id for c in published_refs],
            }
        ),
        encoding="utf-8",
    )


def test_issued_tool_unknown_outcome_blocks_replay(qwen_dev):
    settings, folder, scope, manifest = qwen_dev
    report = report_scope(scope, manifest)
    rpath = folder / "uncertain-report.json"
    rpath.write_text(report.model_dump_json(), encoding="utf-8")
    run_id = str(uuid4())
    probe(
        "start",
        run_id,
        rpath,
        "--rag-scope",
        str(folder / "scope.json"),
        "--cut",
        "tool_issued",
        expected=91,
    )
    result = probe("resume", run_id, rpath, "--rag-scope", str(folder / "scope.json"), expected=2)
    assert result["error"]["code"] == "RECOVERY_UNCERTAIN"


def test_real_qwen_cache_concurrency_database_timeout_and_exit(qwen_dev):
    """One real model, bounded concurrent use, known PG rollback; no receipt fabrication."""
    import sqlalchemy as sa

    settings, folder, scope, _ = qwen_dev
    # Trigger statement_timeout before the existing 500ms lock_timeout. Both are
    # fail-closed; this case specifically verifies the known-rollback timeout code.
    settings = settings.model_copy(update={"query_timeout_seconds": 0.25})

    async def check():
        begin = time.perf_counter()
        async with rag_session(settings, scope, goal=QUESTION) as tools:
            ready = time.perf_counter()
            first = await tools.search(QUESTION, 3)
            second = await tools.search(QUESTION, 3)
            assert first.documents and second.documents
            assert first.embedding_usage.calls == 2 and second.embedding_usage.calls == 1
            assert [d.citation.goal_score for d in first.documents] == [
                d.citation.goal_score for d in second.documents
            ]
            pair = await asyncio.gather(
                tools.search(QUESTION, 3), tools.search(QUESTION, 3), return_exceptions=True
            )
            assert sum(isinstance(x, AgentFailure) for x in pair) == 1
            assert (
                next(x for x in pair if isinstance(x, AgentFailure)).error.code == "EMBEDDING_BUSY"
            )
            with pytest.raises(AgentFailure) as failed:
                async with rag_session(settings, scope, goal=QUESTION):
                    pytest.fail("A second model was admitted to this deployment")
            assert failed.value.error.code == "EMBEDDING_BUSY"
            # Only the new test DB is locked. The server must roll back this SELECT,
            # not turn a known lock/statement timeout into a successful SearchResult.
            engine = sa.create_engine(os.environ["DATAPILOT_OWNER_DATABASE_URL"])
            try:
                with engine.begin() as conn:
                    conn.exec_driver_sql("LOCK TABLE rag.chunks_1024 IN ACCESS EXCLUSIVE MODE")
                    before = time.perf_counter()
                    with pytest.raises(AgentFailure) as pg_error:
                        await tools.search(QUESTION, 3)
                    assert pg_error.value.error.code == "RAG_QUERY_TIMEOUT"
                    pg_seconds = time.perf_counter() - before
                    assert pg_seconds < 10
            finally:
                engine.dispose()
            assert (await tools.search(QUESTION, 3)).documents
            health = (await tools.call("health", {}))["embedding"]
            assert health["loads"] == 1 and health["state"] == "ready"
            close = time.perf_counter()
        data = {
            "ready_seconds": ready - begin,
            "cleanup_seconds": time.perf_counter() - close,
            "known_pg_timeout_seconds": pg_seconds,
            "startup": tools.startup_trace,
            "health": health,
        }
        assert data["cleanup_seconds"] < 5
        (folder / "capacity-and-cache.json").write_text(json.dumps(data), encoding="utf-8")

    run_async(check())


@pytest.mark.parametrize("fault", ["child_exit", "client_disconnect"])
def test_real_qwen_child_exit_and_client_disconnect_have_bounded_cleanup(qwen_dev, fault):
    settings, folder, scope, _ = qwen_dev

    async def check():
        ready = asyncio.Event()
        owners = []

        async def connected():
            async with rag_session(settings, scope, goal=QUESTION) as tools:
                owners.append(tools.process_owner)
                ready.set()
                if fault == "child_exit":
                    tools.process_owner.kill()
                    with pytest.raises(AgentFailure) as rejected:
                        await tools.search(QUESTION, 3)
                    assert rejected.value.error.code == "TOOL_ERROR"
                else:
                    await asyncio.Event().wait()

        task = asyncio.create_task(connected())
        wait = asyncio.create_task(ready.wait())
        done, _ = await asyncio.wait([task, wait], return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            await task  # Surface startup failures rather than hanging the test.
        begin = time.perf_counter()
        if fault == "client_disconnect":
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            assert fault == "client_disconnect"
        except AgentFailure as exc:
            assert exc.error.code == "TOOL_ERROR"  # SDK close after genuine EOF.
        finally:
            wait.cancel()
            await asyncio.gather(wait, return_exceptions=True)
        data = {
            "fault": fault,
            "cleanup_seconds": time.perf_counter() - begin,
            "owner_events": owners[0].events,
        }
        assert data["cleanup_seconds"] < 5
        assert not owners[0].handles
        (folder / (fault + ".json")).write_text(json.dumps(data), encoding="utf-8")

    run_async(check())


@pytest.mark.parametrize(
    "mode,cancel",
    [("encode_delay", False), ("encode_delay", True), ("encode_gil", False), ("init_delay", True)],
)
def test_real_mcp_delayed_model_timeout_and_cancellation_fail_closed(
    qwen_dev, mode, cancel, monkeypatch
):
    settings, folder, scope, _ = qwen_dev
    env = server_environment(settings)
    env.update(
        DATAPILOT_RAG_READER_DATABASE_URL=settings.rag_reader_database_url.get_secret_value(),
        DATAPILOT_RAG_SCOPE=scope.model_dump_json(),
        DATAPILOT_RAG_GOAL=QUESTION,
        DATAPILOT_TEST_QWEN_FAULT=mode,
    )
    import secrets

    token = secrets.token_hex(16)
    env["DATAPILOT_MCP_SESSION_TOKEN"] = token
    env["PYTHONPATH"] = str(ROOT / "src")
    from datapilot.runtime import mcp_client

    original_parameters = mcp_client.StdioServerParameters

    def parameters(**kwargs):
        kwargs["args"] = [str(ROOT / "tests/qwen_delay_server.py")]
        kwargs["command"] = interpreter()
        return original_parameters(**kwargs)

    monkeypatch.setattr(mcp_client, "StdioServerParameters", parameters)

    async def check():
        measured = None
        finished = None
        try:
            async with mcp_client._connection(
                settings,
                env,
                partial(MCPRetrievalTools, scope=scope, goal=QUESTION, session_token=token),
            ) as tools:
                # Real PG source/manifest validation precedes injected delay.
                await tools.preflight()
                owner = tools.process_owner
                if mode != "init_delay":
                    await tools.prepare()
                before = time.perf_counter()
                pending = asyncio.create_task(
                    tools.prepare() if mode == "init_delay" else tools.search(QUESTION, 3)
                )
                if cancel:
                    await asyncio.sleep(0.2)
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
                    outcome = "cancelled"
                else:
                    with pytest.raises(AgentFailure) as failed:
                        await pending
                    assert failed.value.error.code in {"TOOL_TIMEOUT", "TOOL_ERROR"}
                    outcome = failed.value.error.code
                elapsed = time.perf_counter() - before
                assert elapsed < 13
                finished = time.perf_counter()
                measured = {
                    "mode": mode,
                    "cancel": cancel,
                    "outcome": outcome,
                    "call_seconds": elapsed,
                    "backend": "injected delay in real MCP; not Qwen quality inference",
                }
        except AgentFailure as close_error:
            # The original wrapper safely translates late SDK shutdown failures.
            assert measured is not None and close_error.error.code == "TOOL_ERROR"
            measured["shutdown_error"] = close_error.error.code
        measured["cleanup_seconds"] = time.perf_counter() - finished
        measured["owner_events"] = owner.events
        assert measured["cleanup_seconds"] < 5, measured
        # A fresh session must be able to obtain the original PG capacity lock.
        import sqlalchemy as sa

        from datapilot.rag.lifecycle import RESOURCE_LOCK

        engine = sa.create_engine(settings.rag_reader_database_url.get_secret_value())
        try:
            with engine.connect() as conn:
                assert conn.execute(
                    sa.text("SELECT pg_try_advisory_lock(:a,:b)"),
                    {"a": RESOURCE_LOCK[0], "b": RESOURCE_LOCK[1]},
                ).scalar_one()
                conn.execute(
                    sa.text("SELECT pg_advisory_unlock(:a,:b)"),
                    {"a": RESOURCE_LOCK[0], "b": RESOURCE_LOCK[1]},
                )
        finally:
            engine.dispose()
        return measured

    begin = time.perf_counter()
    measured = run_async(check())
    measured["session_seconds"] = time.perf_counter() - begin
    (folder / f"{mode}-{'cancel' if cancel else 'timeout'}.json").write_text(
        json.dumps(measured),
        encoding="utf-8",
    )
