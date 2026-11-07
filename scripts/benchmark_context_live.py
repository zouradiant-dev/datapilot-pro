"""Opt-in paid model experiment: controlled history replay, not an autonomous benchmark."""

import argparse
import asyncio
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.context import ContextManager, closed_batches, measure_context
from datapilot.orchestration.context_contracts import AuthoritySnapshot
from datapilot.orchestration.contracts import BudgetLimits, TaskEnvelope, TaskResult, TaskSpec
from datapilot.orchestration.coordinator import Coordinator
from datapilot.orchestration.loop import (
    WorkerContext,
    WorkerLimits,
    build_worker_loop,
    initial_messages,
)
from datapilot.orchestration.model import Gateway, live_transport
from datapilot.orchestration.runtime import ArtifactStore, Cancellation, Trace, text_hash
from datapilot.orchestration.tools import CAPABILITIES, ToolRegistry
from datapilot.runtime.mcp_client import database_session


@dataclass
class Snapshot:
    envelope: TaskEnvelope
    registry: ToolRegistry
    prefix: list
    messages: list
    expected_ref: str | None


class Calibration:
    """Local summary double ONLY for selecting a host quota. Zero provider requests."""

    async def respond(self, messages, tools):
        assert messages[0].content.startswith("CONTEXT_SUMMARY_JSON") and not tools
        assert set(json.loads(messages[-1].content)) == {"decision_ids"}
        return AIMessage(
            content=json.dumps({"decisions": []}),
            usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )


class Metered:
    """Observe the original NativeTransport; do not alter prompts or perform API retries."""

    def __init__(self, transport):
        self.transport, self.calls = transport, []

    async def respond(self, messages, tools):
        call = {
            "stage": "summary"
            if messages[0].content.startswith("CONTEXT_SUMMARY_JSON")
            else "worker",
            "input_sha256": text_hash(json.dumps(messages_to_dict(messages), ensure_ascii=False)),
            "estimated_input_tokens": measure_context(messages, tools, 1200)[
                1
            ].estimated_input_tokens,
        }
        started = time.monotonic()
        self.calls.append(call)
        try:
            response = await self.transport.respond(messages, tools)
            call["usage"] = response.usage_metadata
            raw = response.response_metadata.get("token_usage", {})
            call["supplier_usage"] = {
                k: v
                for k, v in raw.items()
                if k
                in {
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                    "prompt_cache_hit_tokens",
                    "prompt_cache_miss_tokens",
                }
                and type(v) is int
            }
            call["finish_reason"] = response.response_metadata.get("finish_reason")
            call["response_model"] = response.response_metadata.get("model_name")
            return response
        finally:
            call["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)


async def snapshot(database, run_id, name, rounds, note_chars, *, budget=None):
    task = TaskSpec(
        task_id=name.lower(),
        worker="sql",
        instruction=(
            "查询客户总数。若最近工具已返回 query artifact，只引用该实际工件完成任务，"
            "不要重复查询或进行无关操作。历史 replay 注释是合成的非权威中间记录。"
            "保留 CNY 和时间右开边界 [2025-10-01,2025-11-01) 的约束，不进行因果推断。"
        ),
    )
    envelope = TaskEnvelope(
        run_id=run_id,
        parent_id=run_id,
        task=task,
        plan_version=1,
        allowed_tools=sorted(CAPABILITIES["sql"]),
        budget=budget if budget is not None else BudgetLimits(calls=4, tokens=100000),
    )
    registry = ToolRegistry(envelope, ArtifactStore(run_id), database=database)
    schema = (await registry.invoke("database_schema", {}))["schema"]
    prefix = initial_messages(envelope, schema)
    messages = list(prefix)
    for index in range(rounds):
        call_id = f"replay_{index}"
        payload = await registry.invoke("database_schema", {}, call_id=call_id)
        note = (
            "HOST-CONSTRUCTED REPLAY NOTE, not a real previous model decision: "
            + "Repeated schema inspection; no business fact or permission changed. " * 50
        )[:note_chars]
        messages.extend(
            [
                AIMessage(
                    content=note,
                    tool_calls=[{"id": call_id, "name": "database_schema", "args": {}}],
                ),
                ToolMessage(
                    content=json.dumps(payload, ensure_ascii=False),
                    tool_call_id=call_id,
                    name="database_schema",
                ),
            ]
        )
    expected = None
    if rounds:
        args = {"sql": "SELECT COUNT(*) AS customer_count FROM customers"}
        payload = await registry.invoke("query_database", args, call_id="replay_query")
        expected = payload["artifact_refs"][0]["artifact_id"]
        messages.extend(
            [
                AIMessage(
                    content="Real MCP query completed; reference its actual artifact.",
                    tool_calls=[{"id": "replay_query", "name": "query_database", "args": args}],
                ),
                ToolMessage(
                    content=json.dumps(payload),
                    tool_call_id="replay_query",
                    name="query_database",
                ),
            ]
        )
    return Snapshot(envelope, registry, prefix, messages, expected)


def clone_registry(source):
    store = ArtifactStore(source.envelope.run_id)
    for artifact in source.registry.store.export().values():
        store.put(artifact)
    registry = ToolRegistry(source.envelope, store, database=source.registry.database)
    registry.refs = list(source.registry.refs)
    registry.context_refs = list(source.registry.context_refs)
    registry.sql_attempts = source.registry.sql_attempts
    return registry


def oversized_replay(source):
    """Injected stress view bypasses production L0. It never modifies a source artifact."""
    payload = json.loads(source.messages[-1].content)
    messages = list(source.prefix)
    for index in range(4):
        view = dict(payload)
        if index < 3:
            view["synthetic_oversized_feedback_not_production_L0"] = (
                "Injected untrusted repeated view, not a business fact. " * 150
            )[:6000]
        call_id = f"oversized_replay_{index}"
        messages.extend(
            [
                AIMessage(
                    content="Host replay of one actual query observation, not a new execution.",
                    tool_calls=[
                        {
                            "id": call_id,
                            "name": "query_database",
                            "args": {"sql": "SELECT COUNT(*) AS customer_count FROM customers"},
                        }
                    ],
                ),
                ToolMessage(content=json.dumps(view), tool_call_id=call_id, name="query_database"),
            ]
        )
    source.messages = messages
    return source


def context(source, settings, registry):
    authority = AuthoritySnapshot.for_worker(
        source.envelope, source.envelope.task.instruction, source.prefix[0].content
    )
    return ContextManager(authority, source.prefix, registry, settings)


async def calibrate(source, settings, target):
    if target == "short":
        return 16000, []
    for chars in range(6500, 60001, 500):
        limits = settings.model_copy(
            update={"max_input_chars": chars, "max_context_tokens": 100000}
        )
        ledger = BudgetLedger(BudgetLimits(calls=4, tokens=100000))
        manager = context(source, limits, clone_registry(source))
        model = Gateway(Calibration(), limits, ledger, Cancellation())
        try:
            prepared = await manager.prepare(
                source.messages, source.registry.schemas(), model, "root"
            )
            if prepared.reservation:
                ledger.release_unissued(prepared.reservation)
        except AgentFailure:
            continue
        levels = manager.stats[-1].levels if manager.stats else []
        highest = levels[-1] if levels else None
        if (target == "L1_L2" and highest in {"L1", "L2"}) or highest == target:
            return chars, levels
    raise ValueError("No safe host context limit can exercise the selected stage")


async def arm(source, settings, ledger, transport, name, enabled, chars, golden):
    # Baseline needs headroom to send the uncompressed view. Record this difference.
    limits = settings.model_copy(
        update={
            "context_compression": enabled,
            "max_input_chars": chars if enabled else 64000,
            "max_context_tokens": 100000,
            "max_model_calls": 4,
            "max_total_tokens": 100000,
        }
    )
    registry = clone_registry(source)
    manager = context(source, limits, registry)
    root_limits = ledger.accounts["root"].limits
    account = ledger.fork(
        name, BudgetLimits(calls=min(4, root_limits.calls), tokens=root_limits.tokens)
    )
    observer = Metered(transport)
    cancel = Cancellation()
    model = Gateway(observer, limits, ledger, cancel)
    model.contexts[account] = manager
    trace = Trace(source.envelope.run_id, [])
    model.trace = trace
    original = messages_to_dict(source.messages)
    source_hashes = {r.artifact_id: r.sha256 for r in [*registry.refs, *registry.context_refs]}
    ctx = WorkerContext(
        source.envelope,
        registry,
        model,
        account,
        WorkerLimits(3, 2, settings.mcp_timeout_seconds),
        cancel,
        trace,
        [],
    )
    started = time.monotonic()
    output = await build_worker_loop().ainvoke(
        {"messages": source.messages, "turns": 0, "done": False}, context=ctx
    )
    final = output.get("final")
    refs = [r for r in registry.refs if final and r.artifact_id in final.artifact_ids]
    query_values = [registry.store.get(r).query for r in refs]
    result = TaskResult(
        run_id=source.envelope.run_id,
        task_id=source.envelope.task.task_id,
        plan_version=1,
        worker="sql",
        status="failed" if output.get("error") else "succeeded",
        error=output.get("error"),
        evidence_refs=refs,
        usage=ledger.snapshot(account),
        attempts=registry.sql_attempts,
    )
    verifier = Coordinator(limits, transport, database=registry.database, run_id=result.run_id)
    verifier.store = registry.store
    verdict = verifier.verify(
        {"run_id": result.run_id, "plan_version": 1, "results": {}, "verifications": {}},
        source.envelope.task,
        result,
    )
    invariant = {
        "canonical_input_unchanged": original == messages_to_dict(source.messages),
        "tool_pairs_valid": bool(closed_batches(output["messages"])),
        "original_artifacts_unchanged": all(
            registry.store.get(ref).model_dump() == source.registry.store.get(ref).model_dump()
            for ref in [*source.registry.refs, *source.registry.context_refs]
        ),
        "archives_complete": all(
            json.loads(manager.read_archive(r))[: len(original)] == original
            for r in registry.context_refs
            if r.artifact_id not in source_hashes and r.kind == "context"
        ),
        "result_matches_independent_sql": bool(query_values)
        and all(q and q.rows == golden.rows and not q.truncated for q in query_values),
        "exact_replay_evidence": source.expected_ref is None
        or (final is not None and final.artifact_ids == [source.expected_ref]),
    }
    return {
        "arm": name,
        "compression_enabled": enabled,
        "admission_chars": limits.max_input_chars,
        "input_sha256": text_hash(json.dumps(original, ensure_ascii=False)),
        "status": result.status,
        "error_code": result.error.code if result.error else None,
        "verification": verdict.status,
        "success": result.status == "succeeded"
        and verdict.status == "passed"
        and all(invariant.values()),
        "invariants": invariant,
        "source_result": golden.rows,
        "evidence_ids": final.artifact_ids if final else [],
        "compression_events": [s.model_dump() for s in manager.stats],
        "usage": ledger.snapshot(account).model_dump(),
        "calls": observer.calls,
        "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
    }


async def benchmark(output, live, only_oversized=False):
    settings = Settings(llm_mode="live" if live else "fake")
    if live and (settings.model_provider != "deepseek" or settings.model != "deepseek-flash"):
        raise ValueError("This experiment requires the explicit DeepSeek Flash profile")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "mode": "real_deepseek_controlled_replay" if live else "local_calibration_only",
        "thinking": "disabled",
        "model": settings.model,
        "started_at": stamp,
        "budget": {"calls": 2, "tokens": 32000}
        if only_oversized
        else {"calls": 20, "tokens": 100000},
        "limitations": [
            "Long histories are host-constructed replay, not autonomous previous model decisions.",
            "Schema/query artifacts are actual read-only MCP/PostgreSQL results, not RAG fixtures.",
            "Baseline admits 64000 chars; compressed arms use a smaller calibrated host limit.",
            "Stage quotas use local summary calibration, never selection by live outcome.",
            "Small sample, shared provider cache; latency and costs are not generalizable.",
            "References are P4 artifacts, not P3 verified metric Evidence or business reports.",
            "Oversized supplement injects view padding past L0, not a normal production output.",
        ],
        "cases": [],
    }
    ledger = BudgetLedger(BudgetLimits(**report["budget"]))
    transport = live_transport(settings) if live else None
    async with database_session(settings) as database:
        golden = await database.execute("SELECT COUNT(customer_id) AS n FROM customers")
        scenarios = [
            ("short", 0, 0),
            ("L1_L2", 12, 0),
            ("L3", 12, 1800),
            ("L4", 4, 1800),
        ]
        if only_oversized:
            scenarios = [("L2", 1, 0)]
        for name, rounds, note in scenarios:
            source = await snapshot(database, f"context-live-{stamp}", name, rounds, note)
            if only_oversized:
                source = oversized_replay(source)
            chars, levels = await calibrate(source, settings, name)
            case = {
                "scenario": name,
                "replay_schema_rounds": rounds,
                "synthetic_note_chars_per_round": note,
                "calibrated_chars": chars,
                "calibrated_levels": levels,
                "replay_input_estimated_tokens": measure_context(
                    source.messages, source.registry.schemas(), settings.max_output_tokens
                )[1].estimated_input_tokens,
                "arms": [],
            }
            report["cases"].append(case)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            if not live:
                print(json.dumps({k: v for k, v in case.items() if k != "arms"}))
                continue
            for repeat in range(1 if name == "short" or only_oversized else 2):
                for enabled in [False, True] if repeat == 0 else [True, False]:
                    label = f"{name.lower()}_{repeat}_{'on' if enabled else 'off'}"
                    record = await arm(
                        source, settings, ledger, transport, label, enabled, chars, golden
                    )
                    case["arms"].append(record)
                    report["usage"] = ledger.snapshot().model_dump()
                    output.write_text(
                        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    print(
                        json.dumps(
                            {
                                "arm": label,
                                "success": record["success"],
                                "usage": record["usage"],
                                "levels": [s["levels"] for s in record["compression_events"]],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
    report["usage"] = ledger.snapshot().model_dump()
    report["finished_at"] = datetime.now(UTC).isoformat()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Explicit opt-in: consumes API credits")
    parser.add_argument("--only-oversized", action="store_true", help="Two-call stress supplement")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    artifacts = Path(__file__).resolve().parents[1] / "artifacts"
    if not output.is_relative_to(artifacts.resolve()) or output.exists():
        parser.error("Choose a new output file inside this repository's artifacts/")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump({"status": "started"}, stream)
    asyncio.run(benchmark(output, args.live, args.only_oversized))


if __name__ == "__main__":
    main()
