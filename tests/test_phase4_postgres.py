"""Real isolated PG/MCP/context/journal; all model decisions and usage are test doubles."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from test_document_fact_postgres import fact_sources as fact_sources
from test_document_fact_postgres import host_fact
from test_rag_postgres import embedding as embedding

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import BudgetLimits
from datapilot.persistence.backend import Backend, DurableLedger, execute
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import RagScope
from datapilot.rag.mcp import rag_session
from datapilot.reporting.contracts import DocumentGoal, ReportScope, confirm_finite_scope

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/p7/phase4-budget-snapshot"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("DATAPILOT_RUN_DB_TESTS") != "1",
        reason="Explicit isolated PostgreSQL opt-in required",
    ),
]


@pytest.fixture(scope="module", autouse=True)
def isolated_probe_output(tmp_path_factory):
    global OUT
    original = OUT
    OUT = tmp_path_factory.mktemp("budget-context-probe")
    yield
    OUT = original


def budget_settings(settings, enabled=True):
    return settings.model_copy(
        update={
            "max_total_tokens": 18000,
            "max_model_calls": 8,
            "max_worker_turns": 4,
            "max_context_tokens": 100000,
            "max_input_chars": 64000,
            "context_keep_batches": 1,
            "context_compression": enabled,
            "context_allow_summary": False,
        }
    )


class BudgetDecisions:
    async def respond(self, messages, tools):
        if messages[0].content.startswith("REPORT_PLAN_JSON"):
            from test_cross_source_postgres import ReportDecisions

            result = await ReportDecisions("").respond(messages, tools)
            result.usage_metadata = {"input_tokens": 600, "output_tokens": 100, "total_tokens": 700}
            return result
        indices = [
            int(c["id"].rsplit("_", 1)[1])
            for m in messages
            if m.type == "ai"
            for c in m.tool_calls
            if c["id"].startswith("phase4_")
        ]
        step = max(indices, default=-1) + 1
        if step == 0:
            name, args = "search_documents", {"query": "访问审计日志必须保留多少年？", "top_k": 5}
        else:
            payload = json.loads(next(m.content for m in reversed(messages) if m.type == "tool"))
            refs = payload.get("artifact_refs") or payload.get("context_refs")
            assert refs
            if step < 3:
                doc_id = (
                    payload["documents"][0]["document_id"]
                    if payload.get("documents")
                    else payload["citation_ref"]["chunk_id"]
                )
                name, args = (
                    "read_context",
                    {
                        "artifact_id": refs[0]["artifact_id"],
                        "document_id": doc_id,
                        "max_chars": 512,
                    },
                )
            else:
                name, args = (
                    "submit_rag_result",
                    {"artifact_ids": [refs[0]["artifact_id"]], "outcome": "complete"},
                )
        return AIMessage(
            content="Synthetic non-authoritative note: " + "x" * (1000 if step < 2 else 0),
            response_metadata={"synthetic_local_metadata": "m" * (800 if step < 2 else 0)},
            tool_calls=[{"id": f"phase4_{step}", "name": name, "args": args}],
            usage_metadata={"input_tokens": 1900, "output_tokens": 100, "total_tokens": 2000},
        )


def inputs(binding):
    rag = RagScope.model_validate_json(json.dumps(binding["scope"]))
    question = "访问审计日志必须保留多少年？"
    scope = ReportScope(
        owner=rag.owner,
        question=question,
        datasets=rag.datasets,
        metrics=[],
        document_goal=DocumentGoal(
            goal_id="documents",
            question=question,
            metric_goals=[],
            purpose="facts",
            required_facts=[
                host_fact(binding, "retention.md", "retention", "访问审计日志必须保留七年")
            ],
        ),
    )
    return rag, scope


def state_rows(settings, run_id, owner):
    backend = Backend(settings.runtime_database_url.get_secret_value(), run_id, owner)
    try:
        with backend.transaction() as conn:
            rows = [
                dict(r)
                for r in execute(
                    conn,
                    "SELECT call_key,kind,tool_name,status,payload_hash FROM execution.calls "
                    "WHERE run_id=:r ORDER BY call_key",
                    r=run_id,
                ).mappings()
            ]
        return rows
    finally:
        backend.close()


@pytest.mark.parametrize("enabled", [False, True])
def test_real_rag_budget_pressure_uses_only_original_limit_and_preserves_facts(
    pg_settings, fact_sources, enabled
):
    rag, scope = inputs(fact_sources)
    if enabled:
        scope = confirm_finite_scope(
            scope, rag, confirmation_ref="public-ci-batch3-budget-pressure-review"
        )
    config = budget_settings(pg_settings, enabled)
    run_id = str(uuid4())
    result = run_async(
        run_durable(
            config,
            run_id,
            scope.question,
            owner=scope.owner,
            rag_scope=rag,
            report_scope=scope,
            transport=BudgetDecisions(),
        )
    )
    rows = state_rows(config, run_id, scope.owner)
    compressions = [e["compression"] for e in result["trace"] if e.get("compression")]
    if enabled:
        assert result["business_completion"].status == "completed"
        assert result["cross_source_report"].claims[0].fact_coverage["retention"] is not None
        assert compressions and any("L3" in c["levels"] for c in compressions)
        assert all(
            c["summary_calls"] == 0 and not c["irreversible_source_loss"] for c in compressions
        )
        assert result["usage"]["calls"] == 5 and result["usage"]["total_tokens"] == 8700
    else:
        assert any(
            r.error and r.error.code == "BUDGET_EXCEEDED" for r in result["results"].values()
        )
        assert result["business_completion"].status != "completed" and not compressions
    assert result["usage"]["total_tokens"] <= 18000
    assert sum(r["tool_name"] == "search_documents" for r in rows) == 1
    assert all(r["status"] == "complete" for r in rows)
    with (OUT / f"{sys.version_info.minor}-budget-{enabled}-{run_id}.json").open(
        "x", encoding="utf-8"
    ) as f:
        json.dump(
            {
                "run_id": run_id,
                "usage": result["usage"],
                "completion": result["business_completion"].model_dump(),
                "compressions": compressions,
                "scope_sha256": digest(scope),
                "calls": rows,
            },
            f,
            indent=2,
        )


def probe(action, run_id, path, *extra, expected=0):
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/budget_context_probe.py"),
            action,
            run_id,
            str(path),
            *extra,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )
    assert proc.returncode == expected, proc.stdout[-500:] + proc.stderr[-1200:]
    return json.loads(proc.stdout) if proc.stdout.strip() else None


@pytest.mark.parametrize("cut", [None, "tool_committed", "model_response"])
def test_compacted_durable_restore_keeps_known_results_or_blocks_unknown(
    pg_settings, fact_sources, cut
):
    rag, scope = inputs(fact_sources)
    # Review the same finite public audit-retention contract before persisting it;
    # keep all original budget, crash, wrong-version and no-reissue assertions.
    scope = confirm_finite_scope(scope, rag, confirmation_ref="public-ci-budget-recovery-review")
    run_id = str(uuid4())
    path = OUT / f"input-{run_id}.json"
    path.write_text(
        json.dumps(
            {
                "rag_scope": rag.model_dump(mode="json"),
                "report_scope": scope.model_dump(mode="json"),
            }
        ),
        encoding="utf-8",
    )
    extra = ["--pause"] if cut is None else ["--cut", cut]
    before = probe("start", run_id, path, *extra, expected=0 if cut is None else 91)
    if cut == "model_response":
        stopped = probe("resume", run_id, path, expected=2)
        assert stopped["error"] == "RECOVERY_UNCERTAIN"
        rows = state_rows(pg_settings, run_id, scope.owner)
        again = probe("resume", run_id, path, expected=2)
        assert again == stopped and state_rows(pg_settings, run_id, scope.owner) == rows
        backend = Backend(pg_settings.runtime_database_url.get_secret_value(), run_id, scope.owner)
        try:
            usage = DurableLedger(backend, BudgetLimits(calls=8, tokens=18000)).snapshot()
            assert usage.total_tokens > 0 and not usage.usage_complete
        finally:
            backend.close()
    else:
        if cut is None:
            changed = json.loads(path.read_bytes())
            changed["rag_scope"]["corpora"][0]["index_version"] = "0" * 64
            other = OUT / f"changed-{run_id}.json"
            other.write_text(json.dumps(changed), encoding="utf-8")
            calls_before = state_rows(pg_settings, run_id, scope.owner)
            refused = probe("resume", run_id, other, expected=2)
            assert refused["error"] == "DOCUMENT_NOT_AUTHORIZED"
            assert state_rows(pg_settings, run_id, scope.owner) == calls_before
        result = probe("resume", run_id, path)
        rows = state_rows(pg_settings, run_id, scope.owner)
        repeated = probe("resume", run_id, path, "--no-model")
        assert (
            result["usage"] == repeated["usage"]
            and result["report_sha256"] == repeated["report_sha256"]
        )
        assert state_rows(pg_settings, run_id, scope.owner) == rows
        assert result["business_completion"] == "completed" and result["usage"]["calls"] == 5
        assert sum(r["tool_name"] == "search_documents" for r in rows) == 1
        assert sum(r["tool_name"] == "read_context" for r in rows) == 2
        if before:
            assert before["usage"] == result["usage"]


def test_pinned_source_validity_and_unattested_snapshot_remain_independent(
    pg_settings, fact_sources
):
    from test_cross_source_postgres import ReportDecisions

    rag, scope = inputs(fact_sources)

    async def check():
        async with rag_session(pg_settings, rag, goal=scope.question) as tools:
            result = await tools.search(scope.question, 5)
            assert result.documents and all(
                d.citation.index_version == rag.corpora[0].index_version for d in result.documents
            )

    run_async(check())
    changed = rag.model_copy(deep=True)
    changed.corpora[0].index_version = "0" * 64

    async def denied():
        async with rag_session(pg_settings, changed, goal=scope.question):
            pytest.fail("Changed source became authorized")

    with pytest.raises(AgentFailure):
        run_async(denied())
    scope.question = scope.document_goal.question = "分析已经固定的最新审计日志文档快照。"
    result = run_async(
        run_durable(
            budget_settings(pg_settings),
            str(uuid4()),
            scope.question,
            owner=scope.owner,
            rag_scope=rag,
            report_scope=scope,
            transport=ReportDecisions("访问审计日志必须保留多少年？"),
        )
    )
    assert result["business_completion"].status != "completed"
    assert result["business_completion"].missing_evidence["documents"] == ["snapshot_not_attested"]


def test_durable_remaining_refreshes_pending_sibling_reservations(pg_settings):
    run_id = str(uuid4())
    limits = BudgetLimits(calls=8, tokens=18000)
    backend = Backend(pg_settings.runtime_database_url.get_secret_value(), run_id, "local-user")
    try:
        backend.register({"test": "phase4-headroom-only"}, limits)
        a = DurableLedger(backend, limits)
        a.fork("a", limits)
        a.fork("b", limits)
        stale = DurableLedger(backend, limits)
        ticket = a.reserve_batch("b", [(3000, 1000)])[0]
        assert stale.remaining("a") == (7, 14000)
        a.release_unissued(ticket)
        assert stale.remaining("a") == (8, 18000)
    finally:
        backend.close()
