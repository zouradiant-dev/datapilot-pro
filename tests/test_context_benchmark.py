"""Local runner checks only; these fixtures never call a supplier or PostgreSQL."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from datapilot.contracts import QueryResult
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.contracts import BudgetLimits

spec = importlib.util.spec_from_file_location(
    "context_benchmark", Path(__file__).resolve().parents[1] / "scripts/benchmark_context_live.py"
)
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)


class DatabaseDouble:
    async def schema(self):
        return "customers(customer_id INTEGER); " + "synthetic schema metadata " * 60

    async def execute(self, sql):
        return QueryResult(columns=["n"], rows=[[240]], row_count=1, truncated=False, elapsed_ms=0)


class ModelDouble:
    async def respond(self, messages, tools):
        if messages[0].content.startswith("CONTEXT_SUMMARY_JSON"):
            content = json.loads(messages[-1].content)["expected"]
            content["decisions"] = []
        else:
            ref = json.loads(messages[-1].content)["artifact_refs"][0]["artifact_id"]
            content = {"artifact_ids": [ref]}
        return AIMessage(
            content=json.dumps(content),
            usage_metadata={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            response_metadata={"token_usage": {"prompt_cache_hit_tokens": 12}},
        )


@pytest.mark.parametrize(
    "target,rounds,note", [("L1_L2", 12, 0), ("L2", 1, 0), ("L3", 12, 1800), ("L4", 4, 1800)]
)
async def test_replay_pair_has_identical_input_and_artifacts_and_records_summary(
    settings, target, rounds, note
):
    source = await bench.snapshot(DatabaseDouble(), "benchmark-test", target, rounds, note)
    if target == "L2":
        source = bench.oversized_replay(source)
    settings = settings.model_copy(update={"max_total_tokens": 100000})
    chars, levels = await bench.calibrate(source, settings, target)
    assert levels and (target == "L1_L2" or levels[-1] == target)
    ledger = BudgetLedger(BudgetLimits(calls=8, tokens=100000))
    golden = await DatabaseDouble().execute("independent fixture")
    records = [
        await bench.arm(
            source, settings, ledger, ModelDouble(), str(enabled), enabled, chars, golden
        )
        for enabled in (False, True)
    ]
    assert all(r["success"] for r in records)
    assert records[0]["input_sha256"] == records[1]["input_sha256"]
    assert records[0]["evidence_ids"] == records[1]["evidence_ids"]
    assert not records[0]["compression_events"] and records[1]["compression_events"]
    assert records[1]["calls"][0]["supplier_usage"]["prompt_cache_hit_tokens"] == 12
    assert records[1]["usage"]["calls"] == (2 if target == "L4" else 1)
    assert not ledger.pending


async def test_runner_preserves_failure_without_retry_or_claiming_success(settings):
    class BrokenSummary(ModelDouble):
        async def respond(self, messages, tools):
            response = await super().respond(messages, tools)
            if messages[0].content.startswith("CONTEXT_SUMMARY_JSON"):
                body = json.loads(response.content)
                body["allowed_tools"] = ["shell"]
                response.content = json.dumps(body)
            return response

    source = await bench.snapshot(DatabaseDouble(), "benchmark-failure", "L4", 4, 1800)
    chars, _ = await bench.calibrate(source, settings, "L4")
    ledger = BudgetLedger(BudgetLimits(calls=4, tokens=100000))
    result = await bench.arm(
        source,
        settings,
        ledger,
        BrokenSummary(),
        "invalid",
        True,
        chars,
        await DatabaseDouble().execute("fixture"),
    )
    assert not result["success"] and result["error_code"] == "CONTEXT_LIMIT"
    assert result["usage"]["calls"] == 1 and len(result["calls"]) == 1
    assert not ledger.pending
