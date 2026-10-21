"""Real PG17/pgvector + pinned local neural embedding + real MCP; LLM decisions labeled."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import sqlalchemy as sa
from langchain_core.messages import AIMessage
from test_semantic_integration import metric_data as metric_data

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetBinding, DatasetScope
from datapilot.db.management import management_url
from datapilot.graph import run_question
from datapilot.orchestration.contracts import Plan, TaskSpec
from datapilot.persistence.session import run_async
from datapilot.rag.contracts import Chunker, RagScope, Target
from datapilot.rag.mcp import rag_session
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService, Repository, make_pin, sql

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "tests/fixtures/rag"


@pytest.fixture(scope="session")
def embedding():
    # Never replace missing weights with vectors, and never download implicitly from a test.
    return LocalEmbedding()


@pytest.fixture
def rag_data(pg_settings, embedding):
    target = Target(corpus_id=str(uuid4()))
    scope = RagScope(allow_saas=True)
    service = IngestionService(management_url("rag_ingest"), embedding)
    paths = [SOURCES / n for n in ("onboarding.md", "billing.md", "release.md")]
    manifest, version, reused, _ = service.ingest(target, paths, scope=scope, reviewed=True)
    assert not reused and not manifest.model.fixture
    scope.corpora = [make_pin(manifest, version)]
    yield target, scope, service, paths, manifest
    service.close()


def test_real_neural_embedding_dimensions_no_truncation_and_similarity(pg_settings, embedding):
    vectors, usage = embedding.encode(
        ["新客户入门培训能降低上手门槛。", "仪表盘缓存提升报表加载速度。"]
    )
    query, _ = embedding.encode(["如何帮助首次使用的顾客学习软件？"], query=True)
    assert vectors.shape == (2, 512) and np.allclose(np.linalg.norm(vectors, axis=1), 1)
    assert float(vectors[0] @ query[0]) > float(vectors[1] @ query[0])
    assert usage.tokens > 0 and usage.mode == "local_onnx"
    with pytest.raises(AgentFailure, match="truncation"):
        embedding.encode(["新" * 512], query=True)


def test_real_mcp_multidocument_synonyms_and_original_locations(pg_settings, rag_data):
    _, scope, _, paths, manifest = rag_data
    gold = [
        ("客户首次使用怎样更快体会产品价值？", "onboarding.md"),
        ("有哪些改善顾客续订意愿的候选措施？", "onboarding.md"),
        ("已付款账单和经常性订阅金额有什么区别？", "billing.md"),
        ("新版本如何改善仪表板的响应？", "release.md"),
    ]

    async def check():
        async with rag_session(pg_settings, scope) as tools:
            listing = await tools.session.list_tools()
            assert {t.name for t in listing.tools} == {
                "health",
                "search_documents",
                "get_rag_manifest",
            }
            for question, expected in gold:
                result = await tools.search(question, 2)
                assert (
                    not result.fixture
                    and result.documents
                    and result.documents[0].source == expected
                )
                for doc in result.documents:
                    c = doc.citation
                    raw = next(p for p in paths if p.name == doc.source).read_bytes()
                    text = raw.decode("utf-8-sig")
                    assert text[c.start : c.end] == doc.text
                    assert hashlib.sha256(raw).hexdigest() == c.source_sha256 == c.version
                    assert hashlib.sha256(doc.text.encode()).hexdigest() == doc.sha256 == c.sha256
                    assert (
                        c.page is None
                        and c.score >= scope.min_score
                        and c.index_version == scope.corpora[0].index_version
                    )
                tools.validate_result(result)
            with pytest.raises(AgentFailure, match="allowed"):
                await tools.call("query_database", {"sql": "SELECT 1"})
            altered = result.model_copy(deep=True)
            altered.documents[0].citation.line_start += 1
            with pytest.raises(AgentFailure):
                tools.validate_result(altered)

    run_async(check())


def test_versions_reingest_and_chunker_rebuild_retain_old_snapshots(
    pg_settings, rag_data, tmp_path
):
    target, scope, service, paths, manifest = rag_data
    old = scope.corpora[0].index_version
    assert service.ingest(target, paths, scope=scope, reviewed=True)[2]
    newpaths = []
    for path in paths:
        new = tmp_path / path.name
        new.write_bytes(
            path.read_bytes()
            + ("\n新增客户工作坊计划。".encode() if path.name == "onboarding.md" else b"")
        )
        newpaths.append(new)
    changed, version, _, _ = service.ingest(target, newpaths, scope=scope, reviewed=True)
    assert version != old
    rebuilt, rebuilt_version, _, _ = service.ingest(
        target, paths, scope=scope, reviewed=True, chunker=Chunker(chars=96)
    )
    assert rebuilt_version not in {old, version}
    repository = Repository(pg_settings.rag_reader_database_url.get_secret_value(), scope)
    try:
        assert repository.manifests()[target.corpus_id] == manifest
        with repository.read() as conn:
            assert (
                sql(
                    conn, "SELECT count(*) FROM rag.indexes WHERE corpus_id=:c", c=target.corpus_id
                ).scalar_one()
                == 3
            )
    finally:
        repository.close()


def test_empty_retrieval_and_invalid_query_are_explicit(pg_settings, embedding, tmp_path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    service = IngestionService(management_url("rag_ingest"), embedding)
    target = Target(corpus_id=str(uuid4()))
    scope = RagScope(allow_saas=True)
    try:
        m, v, _, _ = service.ingest(target, [path], scope=scope, reviewed=True)
        scope.corpora = [make_pin(m, v)]

        async def check():
            async with rag_session(pg_settings, scope) as tools:
                result = await tools.search("客户入门", 3)
                assert not result.documents and result.unavailable_reason == "no_matches"
                with pytest.raises(AgentFailure):
                    await tools.search(" ", 3)
            async with rag_session(pg_settings, RagScope()) as tools:
                result = await tools.search("客户入门", 1)
                assert result.unavailable_reason == "no_authorized_documents"

        run_async(check())
    finally:
        service.close()


def test_document_owner_scope_and_forged_index_are_denied(pg_settings, rag_data):
    _, scope, _, _, _ = rag_data
    for change in ("owner", "version", "documents"):
        altered = scope.model_copy(deep=True)
        if change == "owner":
            altered.owner = "not-delegated"
        elif change == "version":
            altered.corpora[0].index_version = "0" * 64
        else:
            altered.corpora[0].document_ids.append("0" * 64)

        async def check(altered=altered):
            async with rag_session(pg_settings, altered):
                pytest.fail("Forged source scope accepted")

        with pytest.raises(AgentFailure, match="scope|index|delegat"):
            run_async(check())


def test_dataset_scope_is_required_even_when_corpus_id_is_known(
    pg_settings, embedding, metric_data
):
    schema, _, _, _ = metric_data
    target = Target(
        corpus_id=str(uuid4()), dataset_id=schema.dataset_id, dataset_version=schema.version
    )
    scope = RagScope(
        datasets=DatasetScope(
            bindings=[DatasetBinding(dataset_id=schema.dataset_id, version=schema.version)]
        )
    )
    service = IngestionService(management_url("rag_ingest"), embedding)
    try:
        m, v, _, _ = service.ingest(target, [SOURCES / "onboarding.md"], scope=scope, reviewed=True)
        scope.corpora = [make_pin(m, v)]

        async def check():
            async with rag_session(pg_settings, scope) as tools:
                assert (await tools.search("客户首次使用怎样更快体会产品价值？", 1)).documents

        run_async(check())
        rejected = scope.model_copy(update={"datasets": DatasetScope(), "allow_saas": True})

        async def deny():
            async with rag_session(pg_settings, rejected):
                pytest.fail("Cross dataset grant accepted")

        with pytest.raises(AgentFailure, match="scope"):
            run_async(deny())
    finally:
        service.close()


def test_ingest_without_review_or_target_grant_is_denied(rag_data):
    target, scope, service, paths, _ = rag_data
    with pytest.raises(AgentFailure):
        service.ingest(target, paths, scope=scope)
    with pytest.raises(AgentFailure):
        service.ingest(target, paths, scope=RagScope(), reviewed=True)


def test_ingest_rolls_back_after_partial_source_writes(pg_settings, embedding, monkeypatch):
    import datapilot.rag.storage as storage

    original = storage.sql
    target = Target(corpus_id=str(uuid4()))
    service = IngestionService(management_url("rag_ingest"), embedding)

    def fail(conn, statement, **params):
        if statement.startswith("INSERT INTO rag.indexes"):
            raise AgentFailure("INJECTED_FAILURE", "Synthetic failure after source insert")
        return original(conn, statement, **params)

    monkeypatch.setattr(storage, "sql", fail)
    try:
        with pytest.raises(AgentFailure, match="Synthetic"):
            service.ingest(
                target, [SOURCES / "onboarding.md"], scope=RagScope(allow_saas=True), reviewed=True
            )
        with service.read() as conn:
            assert (
                original(
                    conn, "SELECT count(*) FROM rag.corpora WHERE corpus_id=:c", c=target.corpus_id
                ).scalar_one()
                == 0
            )
            assert (
                original(
                    conn, "SELECT count(*) FROM rag.sources WHERE corpus_id=:c", c=target.corpus_id
                ).scalar_one()
                == 0
            )
    finally:
        service.close()


def test_real_pg_timeout_is_known_rolled_back_and_retryable(pg_settings, rag_data, monkeypatch):
    _, scope, _, _, _ = rag_data
    repository = Repository(
        pg_settings.rag_reader_database_url.get_secret_value(), scope, timeout=0.02
    )
    try:
        with pytest.raises(AgentFailure) as exc:
            with repository.read() as conn:
                conn.exec_driver_sql(
                    "SELECT pg_sleep(0.1)"
                )  # Host fault injection, never a model tool.
        assert exc.value.error.code == "RAG_QUERY_TIMEOUT" and exc.value.error.retryable
        assert repository.manifests()
    finally:
        repository.close()


def test_reader_ingest_sql_and_runtime_roles_remain_separated(pg_settings, rag_data):
    _, scope, service, _, _ = rag_data
    reader = Repository(pg_settings.rag_reader_database_url.get_secret_value(), scope)
    try:
        with reader.read() as conn:
            assert conn.exec_driver_sql("SHOW transaction_read_only").scalar_one() == "on"
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                assert not sql(
                    conn, "SELECT has_table_privilege(current_user,'rag.chunks',:p)", p=privilege
                ).scalar_one()
            assert not sql(
                conn, "SELECT has_schema_privilege(current_user,'saas','USAGE')"
            ).scalar_one()
        with service.engine.connect() as conn:
            assert not conn.exec_driver_sql(
                "SELECT has_schema_privilege(current_user,'rag','CREATE')"
            ).scalar_one()
            assert not conn.exec_driver_sql(
                "SELECT has_table_privilege(current_user,'rag.sources','DELETE')"
            ).scalar_one()
    finally:
        reader.close()


@pytest.mark.parametrize("kind", ["original", "chunk", "vector"])
def test_tampered_source_chunk_or_vector_is_rejected(pg_settings, rag_data, kind):
    target, scope, _, _, _ = rag_data
    engine = sa.create_engine(management_url("owner"), hide_parameters=True)
    try:
        with engine.begin() as conn:
            if kind == "original":
                sql(
                    conn,
                    "UPDATE rag.sources SET raw=:raw WHERE corpus_id=:c",
                    raw=b"tampered",
                    c=target.corpus_id,
                )
            elif kind == "chunk":
                sql(
                    conn,
                    "UPDATE rag.chunks SET text='tampered' WHERE corpus_id=:c",
                    c=target.corpus_id,
                )
            else:
                vector = json.dumps([1.0] + [0.0] * 511)
                sql(
                    conn,
                    "UPDATE rag.chunks SET embedding=CAST(:v AS public.vector) WHERE corpus_id=:c",
                    v=vector,
                    c=target.corpus_id,
                )

        async def check():
            async with rag_session(pg_settings, scope) as tools:
                await tools.search("客户首次使用怎样更快体会产品价值？", 5)

        with pytest.raises(AgentFailure, match="hash|chunk|span|snapshot"):
            run_async(check())
    finally:
        engine.dispose()


def test_confirmed_pg_timeout_recovers_via_the_same_real_mcp_session(pg_settings, rag_data):
    _, scope, _, _, _ = rag_data
    engine = sa.create_engine(management_url("owner"), hide_parameters=True)
    short = pg_settings.model_copy(update={"query_timeout_seconds": 0.05})
    with engine.connect() as blocker:
        transaction = blocker.begin()
        blocker.exec_driver_sql("LOCK TABLE rag.chunks IN ACCESS EXCLUSIVE MODE")

        async def check():
            async with rag_session(short, scope) as tools:
                with pytest.raises(AgentFailure) as stopped:
                    await tools.search("客户首次使用怎样更快体会产品价值？", 1)
                assert (
                    stopped.value.error.code == "RAG_QUERY_TIMEOUT"
                    and stopped.value.error.retryable
                )
                transaction.rollback()
                assert (await tools.search("客户首次使用怎样更快体会产品价值？", 1)).documents

        try:
            run_async(check())
        finally:
            if transaction.is_active:
                transaction.rollback()
    engine.dispose()


def test_prompt_injection_text_cannot_delegate_sql(pg_settings, embedding):
    service = IngestionService(management_url("rag_ingest"), embedding)
    scope = RagScope(allow_saas=True, min_score=-1)
    target = Target(corpus_id=str(uuid4()))
    try:
        m, v, _, _ = service.ingest(target, [SOURCES / "injection.md"], scope=scope, reviewed=True)
        scope.corpora = [make_pin(m, v)]

        class Attacker:
            async def respond(self, messages, tools):
                if messages[0].content.startswith("PLAN_JSON"):
                    return AIMessage(
                        content=Plan(
                            tasks=[
                                TaskSpec(task_id="rag", worker="rag", instruction="检索安全文档")
                            ]
                        ).model_dump_json()
                    )
                if messages[-1].type == "tool":
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "id": "injected_sql",
                                "name": "query_database",
                                "args": {"sql": "DELETE FROM customers"},
                            }
                        ],
                    )
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "retrieve_attack",
                            "name": "search_documents",
                            "args": {"query": "安全指令", "top_k": 1},
                        }
                    ],
                )

        async def check():
            async with rag_session(pg_settings, scope) as retrieval:
                result = await run_question(
                    pg_settings, "检索安全文档", retrieval=retrieval, transport=Attacker()
                )
                assert result["status"] == "failed"
                assert result["results"]["1:rag"].error.code == "TOOL_FORBIDDEN"
                assert "Ignore all" not in json.dumps(result["trace"])

        run_async(check())
    finally:
        service.close()


def test_real_worker_retrieval_attempts_are_bounded_without_changing_fixture_loops(
    pg_settings, rag_data
):
    _, scope, _, _, _ = rag_data

    class Repeater:
        async def respond(self, messages, tools):
            usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
            if messages[0].content.startswith("PLAN_JSON"):
                return AIMessage(
                    content=Plan(
                        tasks=[
                            TaskSpec(
                                task_id="rag",
                                worker="rag",
                                instruction="客户首次使用怎样更快体会产品价值？",
                            )
                        ]
                    ).model_dump_json(),
                    usage_metadata=usage,
                )
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": f"repeat_{len(messages)}",
                        "name": "search_documents",
                        "args": {"query": "客户首次使用怎样更快体会产品价值？", "top_k": 1},
                    }
                ],
                usage_metadata=usage,
            )

    async def check():
        async with rag_session(pg_settings, scope) as retrieval:
            result = await run_question(
                pg_settings, "检索客户培训文档", retrieval=retrieval, transport=Repeater()
            )
            # rag-submit-v1 permits one correction after a stale closed-phase request.
            # Keep the original hard assertion: only TWO searches may actually execute.
            assert result["results"]["1:rag"].error.code == "RAG_COMPLETION_REPAIR_EXHAUSTED"
            events = [
                e
                for e in result["trace"]
                if e["node"] == "tool" and e.get("tool_name") == "search_documents"
            ]
            assert sum(e["status"] == "succeeded" for e in events) == 2
            assert len(events) == 4
            assert sum(e["error_code"] == "RAG_ATTEMPTS_EXHAUSTED" for e in events) == 2

    run_async(check())


def probe(action, id_, scope, *options, expected=0):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/rag_recovery_probe.py"),
            action,
            id_,
            str(scope),
            *options,
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )
    assert result.returncode == expected, result.stderr[-1500:] + result.stdout[-1500:]
    return json.loads(result.stdout) if result.stdout.strip() else None


@pytest.mark.parametrize("crash", [False, True])
def test_real_rag_persistent_artifacts_cross_process_and_replay(
    pg_settings, rag_data, tmp_path, crash
):
    _, scope, _, _, _ = rag_data
    path = tmp_path / "scope.json"
    path.write_text(scope.model_dump_json(), encoding="utf-8")
    id_ = str(uuid4())
    before = probe(
        "start",
        id_,
        path,
        "--cut-tool-committed" if crash else "--pause",
        expected=91 if crash else 0,
    )
    final = probe("resume", id_, path)
    repeated = probe("resume", id_, path)
    assert final["status"] == "succeeded" and final["completion"]["status"] == "completed"
    assert final["usage"] == repeated["usage"] and final["usage"]["calls"] == 3
    assert final["results"] == repeated["results"]
    if before:
        assert before["results"] == final["results"] and before["usage"] == final["usage"]
    assert "新客户的前十四天" not in json.dumps(final["trace"], ensure_ascii=False)
