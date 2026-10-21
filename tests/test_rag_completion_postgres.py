"""Real PG/neural embedding/MCP; scripted decisions and deliberate process cut points."""

import asyncio
import json
from uuid import uuid4

import pytest
from test_rag_completion import Decisions
from test_rag_postgres import embedding as embedding
from test_rag_postgres import probe
from test_rag_postgres import rag_data as rag_data

from datapilot.contracts import AgentFailure
from datapilot.graph import run_question
from datapilot.ingestion.common import digest
from datapilot.orchestration.rag_completion import retrieval_goal
from datapilot.orchestration.runtime import text_hash
from datapilot.persistence.backend import Backend, execute, json_value
from datapilot.persistence.session import run_async
from datapilot.rag.mcp import rag_session

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("related", [True, False])
def test_real_semantic_retrieval_checks_original_goal_not_model_search_keywords(
    pg_settings,
    rag_data,
    related,
):
    _, scope, _, _, _ = rag_data
    question = "如何帮助首次使用的顾客学习软件？"

    class SearchDecisions(Decisions):
        async def respond(self, messages, tools):
            response = await super().respond(messages, tools)
            for call in response.tool_calls:
                if call["name"] == "search_documents":
                    call["args"] = {
                        "query": "客户首次使用怎样更快体会产品价值？"
                        if related
                        else "已付款账单和经常性订阅金额有什么区别？",
                        "top_k": 1,
                    }
            return response

    async def check():
        async with rag_session(pg_settings, scope, goal=question) as retrieval:
            config = pg_settings.model_copy(
                update={
                    "max_model_calls": 8,
                    "max_worker_turns": 5,
                    "max_replans": 0,
                }
            )
            model = SearchDecisions(["search", "complete", "insufficient"])
            result = await run_question(
                config,
                question,
                transport=model,
                retrieval=retrieval,
                include_artifacts=True,
            )
            task = result["results"]["1:rag"]
            receipt = task.rag_completion
            assert receipt is not None, task.error.code if task.error else task.status
            assert not receipt.business_conclusions_verified
            assert receipt.verdict == ("semantic_retrieval" if related else "insufficient")
            assert result["completion"].status == ("completed" if related else "blocked")
            # An authentic hit for a model-selected unrelated query is insufficient.
            docs = next(a for a in result["artifacts"].values() if a.kind == "documents")
            parsed = docs.documents
            retrieval.validate_result(parsed)
            assert parsed.documents and parsed.documents[0].citation.goal_sha256 == text_hash(
                question
            )
            assert (
                bool(retrieval.qualifying_documents(parsed.documents, retrieval_goal(question)))
                == related
            )
            assert not retrieval.qualifying_documents(
                parsed.documents, retrieval_goal("另一个目标")
            )
            altered = parsed.model_copy(deep=True)
            altered.documents[0].citation.goal_sha256 = "0" * 64
            with pytest.raises(AgentFailure, match="goal"):
                retrieval.validate_result(altered)

    run_async(check())


def test_concurrent_mcp_queries_share_complete_goal_initialization(pg_settings, rag_data):
    _, scope, _, _, _ = rag_data
    question = "如何帮助首次使用的顾客学习软件？"

    async def check():
        async with rag_session(pg_settings, scope, goal=question) as retrieval:
            results = await asyncio.gather(
                *[retrieval.search("客户首次使用怎样更快体会产品价值？", 1) for _ in range(2)]
            )
            for result in results:
                assert retrieval.qualifying_documents(result.documents, retrieval_goal(question))
            assert sum(r.embedding_usage.calls for r in results) == 3

    run_async(check())


def call_counts(settings, id_):
    backend = Backend(settings.runtime_database_url.get_secret_value(), id_, "local-user")
    try:
        with backend.transaction() as conn:
            return (
                execute(
                    conn,
                    "SELECT kind,tool_name,status,count(*) AS n, "
                    "count(*) FILTER (WHERE status='complete' AND NOT "
                    "((payload->>'ordered_json')::jsonb ? 'error')) AS ok FROM execution.calls "
                    "WHERE run_id=:run GROUP BY kind,tool_name,status "
                    "ORDER BY kind,tool_name,status",
                    run=id_,
                )
                .mappings()
                .all()
            )
    finally:
        backend.close()


@pytest.mark.parametrize(
    "scenario,cut,expected_calls",
    [
        ("normal", "rag_submission_committed", 3),
        ("plain", "rag_correction_committed", 4),
        ("malformed", "rag_correction_committed", 4),
        ("two-search", "rag_submission_committed", 4),
        ("closed-search", "rag_submission_committed", 5),
        ("semantic", "rag_submission_committed", 3),
    ],
)
def test_committed_rag_control_restores_across_process_without_duplicate_calls(
    pg_settings,
    rag_data,
    tmp_path,
    scenario,
    cut,
    expected_calls,
):
    _, scope, _, _, _ = rag_data
    path = tmp_path / "scope.json"
    path.write_text(scope.model_dump_json(), encoding="utf-8")
    id_ = str(uuid4())
    options = ("--scenario", scenario)
    probe("start", id_, path, *options, "--cut-point", cut, expected=91)
    result = probe("resume", id_, path, *options)
    before_repeat = [dict(r) for r in call_counts(pg_settings, id_)]
    repeated = probe("resume", id_, path, *options)
    assert result["completion"]["status"] == "completed", {
        k: v["error"]["code"] if v.get("error") else None for k, v in result["results"].items()
    }
    assert result["results"] == repeated["results"] and result["usage"] == repeated["usage"]
    assert result["usage"]["calls"] == expected_calls
    assert before_repeat == [dict(r) for r in call_counts(pg_settings, id_)]
    receipt = result["results"]["1:rag"]["rag_completion"]
    assert receipt["verdict"] == (
        "semantic_retrieval" if scenario == "semantic" else "literal_locator"
    )
    assert receipt["model_response_sha256"] and receipt["relevant_chunk_ids"]
    assert receipt["business_conclusions_verified"] is False
    assert sum(r["n"] for r in before_repeat if r["tool_name"] == "rag_completion_correction") == (
        1 if scenario in {"plain", "malformed", "closed-search"} else 0
    )
    assert sum(
        r["ok"]
        for r in before_repeat
        if r["tool_name"] == "search_documents" and r["status"] == "complete"
    ) == (2 if scenario in {"two-search", "closed-search"} else 1)
    assert "入门培训是" not in json.dumps(result["trace"], ensure_ascii=False)


def test_uncommitted_submission_is_not_assumed_to_have_failed_and_reissued(
    pg_settings,
    rag_data,
    tmp_path,
):
    _, scope, _, _, _ = rag_data
    path = tmp_path / "scope.json"
    path.write_text(scope.model_dump_json(), encoding="utf-8")
    id_ = str(uuid4())
    probe("start", id_, path, "--cut-point", "rag_submission_validated", expected=91)
    result = probe("resume", id_, path, expected=2)
    assert result["error"]["code"] == "RECOVERY_UNCERTAIN"
    rows = call_counts(pg_settings, id_)
    assert sum(r["n"] for r in rows if r["kind"] == "model") == 3
    assert sum(r["n"] for r in rows if r["tool_name"] == "submit_rag_result") == 1


def test_old_rag_protocol_manifest_is_explicitly_rejected(pg_settings, rag_data, tmp_path):
    _, scope, _, _, _ = rag_data
    path = tmp_path / "scope.json"
    path.write_text(scope.model_dump_json(), encoding="utf-8")
    id_ = str(uuid4())
    probe("start", id_, path, "--pause")
    before = [dict(r) for r in call_counts(pg_settings, id_)]
    backend = Backend(pg_settings.runtime_database_url.get_secret_value(), id_, "local-user")
    try:
        with backend.transaction() as conn:
            # Only this test-created run is mutated; never existing user history.
            manifest = execute(
                conn, "SELECT manifest FROM execution.runs WHERE run_id=:run", run=id_
            ).scalar_one()
            manifest.pop("rag_completion_protocol")
            manifest.pop("rag_completion_goal")
            execute(
                conn,
                "UPDATE execution.runs SET manifest=CAST(:manifest AS jsonb),manifest_hash=:hash "
                "WHERE run_id=:run",
                run=id_,
                manifest=json_value(manifest),
                hash=digest(manifest),
            )
    finally:
        backend.close()
    result = probe("resume", id_, path, expected=2)
    assert result["error"]["code"] == "RECOVERY_IDENTITY"
    assert before == [dict(r) for r in call_counts(pg_settings, id_)]
