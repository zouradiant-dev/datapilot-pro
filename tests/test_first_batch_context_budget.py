"""Public context fixtures for one AI response with two closed tool results.

These are explicitly synthetic input messages and ArtifactStore documents, not
private benchmark Runs or simulated business-query results. Only the subsequent
model decision uses the existing explicit ModelDouble; no DB or Provider opens.
"""

import copy
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict
from test_context_engineering import ModelDouble, make_context

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest as view_digest
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.context import (
    ContextManager,
    closed_batches,
    measure_context,
    tool_view,
)
from datapilot.orchestration.contracts import Artifact, BudgetLimits, Document, SearchResult
from datapilot.orchestration.runtime import text_hash
from datapilot.rag.contracts import ChunkCitation


def first_batch(
    settings, *, duplicate=True, available=None, pressure="dedupe", short_body=False, preview=False
):
    config, old_manager, gateway, registry, prefix = make_context(
        settings, max_chars=16000, max_tokens=18000, max_calls=8, model=ModelDouble()
    )
    config = config.model_copy(
        update={
            "max_total_tokens": 18000,
            "max_worker_turns": 4,
            "max_output_tokens": 1200,
        }
    )
    registry.envelope.budget = BudgetLimits(calls=4, tokens=18000)
    manager = ContextManager(old_manager.authority, prefix, registry, config)
    gateway.settings = config
    gateway.contexts["1:r"] = manager

    def document(name, text, score):
        digest = text_hash(text)
        return Document(
            document_id="public-" + name + ("-" + "chunk_" * 12 if short_body else ""),
            source="fixture://public-context/"
            + name
            + ("/" + "lineage/" * 24 if short_body else ""),
            version=digest,
            text=text,
            sha256=digest,
            citation=ChunkCitation(
                chunk_id=digest,
                start=0,
                end=len(text),
                line_start=1,
                line_end=1,
                sha256=digest,
                corpus_id="00000000-0000-4000-8000-000000000017",
                index_version="a" * 64,
                source_id=text_hash("public source " + name),
                document_id=text_hash("public document " + name),
                version=digest,
                source_sha256=digest,
                model_revision="d" * 40,
                chunker_sha256="e" * 64,
                score=score,
            ),
        )

    shared_text = "Public short shared rule." if short_body else "公开合成重叠段落：" + "共" * 220
    unique_a = "Public unique source A rule: " + "a" * 200
    unique_b = "Public unique source B rule: " + "b" * 200
    shared = document("overlap", shared_text, 0.81)
    second = (
        shared.model_copy(update={"citation": shared.citation.model_copy(update={"score": 0.67})})
        if duplicate
        else document("different", "Different independent passage: " + "z" * 220, 0.67)
    )
    results = [
        SearchResult(fixture=True, documents=[shared, document("rule-a", unique_a, 0.72)]),
        SearchResult(fixture=True, documents=[second, document("rule-b", unique_b, 0.74)]),
    ]
    calls = [
        {
            "id": "first_source",
            "name": "search_documents",
            "args": {"query": "public A", "top_k": 2},
        },
        {
            "id": "second_source",
            "name": "search_documents",
            "args": {"query": "public B", "top_k": 2},
        },
    ]
    messages = [*prefix, AIMessage(content="", tool_calls=calls)]
    for call, result in zip(calls, results, strict=True):
        ref = registry.store.put(
            Artifact(
                run_id=registry.envelope.run_id,
                task_id=registry.envelope.task.task_id,
                plan_version=1,
                kind="documents",
                source="fixture/public-first-batch",
                documents=result,
            )
        )
        registry.refs.append(ref)
        payload = (
            tool_view(registry.store.get(ref), ref, 6000)
            if preview
            else {
                "artifact_refs": [ref.model_dump()],
                "document_count": len(result.documents),
                "fixture": True,
                "documents": [d.model_dump() for d in result.documents],
            }
        )
        messages.append(
            ToolMessage(
                tool_call_id=call["id"],
                name=call["name"],
                content=json.dumps(
                    payload,
                    ensure_ascii=False,
                ),
            )
        )
    assert len(messages) == 5 and len(closed_batches(messages)) == 1
    measured = measure_context(messages, registry.schemas(), config.max_output_tokens)[1]
    required = measured.estimated_input_tokens + measured.output_reserved_tokens
    assert required < 18000 and manager.fits(messages, registry.schemas(), ratio=0.8)
    compact = [
        message.model_copy(
            update={
                "content": json.dumps(
                    json.loads(message.content), ensure_ascii=False, separators=(",", ":")
                )
            }
        )
        if message.type == "tool"
        else message
        for message in messages
    ]
    compact_usage = measure_context(compact, registry.schemas(), config.max_output_tokens)[1]
    compact_required = compact_usage.estimated_input_tokens + compact_usage.output_reserved_tokens
    # Whitespace cleanup alone must be insufficient; source text reuse is needed.
    headroom = (
        (compact_required - 128 if pressure == "dedupe" else compact_required + 16)
        if available is None
        else available
    )
    spent = 18000 - headroom
    child_spent = min(1800, spent - 1)
    ledger = BudgetLedger(BudgetLimits(calls=8, tokens=18000))
    ledger.fork("1:r", registry.envelope.budget)
    planner_ticket = ledger.reserve_batch("root", [(0, spent - child_spent)])[0]
    ledger.settle(planner_ticket, spent - child_spent)
    worker_ticket = ledger.reserve_batch("1:r", [(0, child_spent)])[0]
    ledger.settle(worker_ticket, child_spent)
    gateway.ledger = ledger
    return (
        manager,
        gateway,
        registry,
        messages,
        {
            "required": required,
            "compact_required": compact_required,
            "shared": shared_text,
            "unique_a": unique_a,
            "unique_b": unique_b,
        },
    )


def original_artifacts(registry):
    return {
        ref.artifact_id: registry.store.get(ref).model_dump(mode="json") for ref in registry.refs
    }


def expanded_tool_payloads(view):
    """Resolve same-view preview references without reading any external artifact."""
    documents = {}
    payloads = []
    for message in view:
        if message.type != "tool":
            continue
        payload = copy.deepcopy(json.loads(message.content))
        expanded = []
        for index, entry in enumerate(payload.get("documents", [])):
            if "document_ref" in entry:
                pointer = entry["document_ref"]
                base = documents[(pointer["tool_call_id"], pointer["document_index"])]
                assert pointer["view_sha256"] == view_digest(base)
                assert entry["document_id"] == base["document_id"]
                document = copy.deepcopy(base)
                document.update(entry.get("overrides", {}))
                assert document["document_id"] == entry["document_id"]
            else:
                document = entry
            documents[(message.tool_call_id, index)] = document
            expanded.append(document)
        payload["documents"] = expanded
        payloads.append(payload)
    return payloads


@pytest.mark.parametrize("short_body", [False, True])
async def test_first_closed_dual_search_reuses_overlap_without_losing_feedback_or_sources(
    settings, short_body
):
    manager, gateway, registry, messages, content = first_batch(settings, short_body=short_body)
    canonical = messages_to_dict(messages)
    artifacts = original_artifacts(registry)
    before = gateway.ledger.dump_state()
    assert gateway.ledger.remaining("1:r")[1] == content["compact_required"] - 128

    await gateway.invoke(messages, registry.schemas(), "1:r")

    assert len(gateway.transport.requests) == 1
    view = gateway.transport.requests[0]
    text = "\n".join(str(m.content) for m in view)
    assert text.count(content["shared"]) == 1
    assert content["unique_a"] in text and content["unique_b"] in text
    assert "public-overlap" in text and text_hash(content["shared"]) in text
    # Query-specific metadata must not disappear with repeated source text.
    assert "0.81" in text and "0.67" in text
    originals = [json.loads(m.content) for m in messages if m.type == "tool"]
    expanded = expanded_tool_payloads(view)
    assert len(expanded) == len(originals)
    for original, restored in zip(originals, expanded, strict=True):
        assert {key: restored[key] for key in original} == original
    assert view[: len(manager.prefix)] == manager.prefix
    assert [(m.name, m.tool_call_id) for m in view if m.type == "tool"] == [
        ("search_documents", "first_source"),
        ("search_documents", "second_source"),
    ]
    ai = next(m for m in view if m.type == "ai")
    assert ai.tool_calls == messages[len(manager.prefix)].tool_calls
    assert len(closed_batches(view)) == 1
    assert messages_to_dict(messages) == canonical
    assert original_artifacts(registry) == artifacts
    assert gateway.ledger.snapshot().calls == before["accounts"]["root"]["usage"]["calls"] + 1
    assert gateway.ledger.snapshot("1:r").calls == before["accounts"]["1:r"]["usage"]["calls"] + 1
    assert (
        gateway.ledger.snapshot().reported_tokens
        == before["accounts"]["root"]["usage"]["reported_tokens"] + 30
    )
    assert not gateway.ledger.pending
    assert gateway.ledger.accounts["root"].limits == BudgetLimits(calls=8, tokens=18000)
    assert gateway.ledger.accounts["1:r"].limits == BudgetLimits(calls=4, tokens=18000)
    assert manager.stats and manager.stats[-1].summary_calls == 0
    archive = next(
        ref for ref in registry.context_refs if ref.artifact_id == manager.stats[-1].archive_id
    )
    assert json.loads(manager.read_archive(archive)) == canonical


async def test_ample_first_batch_keeps_original_view_even_with_duplicate_text(settings):
    manager, gateway, registry, messages, _ = first_batch(settings)
    gateway.ledger = BudgetLedger(BudgetLimits(calls=8, tokens=18000))
    gateway.ledger.fork("1:r", BudgetLimits(calls=4, tokens=18000))
    canonical = messages_to_dict(messages)
    artifacts = original_artifacts(registry)

    await gateway.invoke(messages, registry.schemas(), "1:r")

    assert messages_to_dict(gateway.transport.requests[0]) == canonical
    assert messages_to_dict(messages) == canonical and original_artifacts(registry) == artifacts
    assert not manager.stats


async def test_first_batch_json_cleanup_preserves_every_parsed_tool_field(settings):
    manager, gateway, registry, messages, content = first_batch(settings, pressure="json")
    canonical = messages_to_dict(messages)
    artifacts = original_artifacts(registry)
    available = gateway.ledger.remaining("1:r")[1]
    assert content["compact_required"] <= available < content["required"]

    await gateway.invoke(messages, registry.schemas(), "1:r")

    view = gateway.transport.requests[0]
    assert len(closed_batches(view)) == 1
    original_tools = [m for m in messages if m.type == "tool"]
    projected_tools = [m for m in view if m.type == "tool"]
    assert len(projected_tools) == 2
    for original, projected in zip(original_tools, projected_tools, strict=True):
        assert (projected.name, projected.tool_call_id) == (original.name, original.tool_call_id)
        assert json.loads(projected.content) == json.loads(original.content)
    assert messages_to_dict(messages) == canonical and original_artifacts(registry) == artifacts
    assert manager.stats[-1].summary_calls == 0


@pytest.mark.parametrize("duplicate", [False, True])
async def test_first_batch_cannot_fit_protected_budget_never_dispatches_or_changes_ledger(
    settings, duplicate
):
    manager, gateway, registry, messages, _ = first_batch(
        settings, duplicate=duplicate, available=150
    )
    canonical = messages_to_dict(messages)
    artifacts = original_artifacts(registry)
    ledger = gateway.ledger.dump_state()
    archives = list(registry.context_refs)

    with pytest.raises(AgentFailure) as exc:
        await gateway.invoke(messages, registry.schemas(), "1:r")

    assert exc.value.error.code == "BUDGET_EXCEEDED"
    assert not gateway.transport.requests and gateway.ledger.dump_state() == ledger
    assert messages_to_dict(messages) == canonical and original_artifacts(registry) == artifacts
    assert registry.context_refs == archives


async def test_disabled_compression_preserves_first_batch_budget_rejection(settings):
    config = settings.model_copy(update={"context_compression": False})
    _, gateway, registry, messages, _ = first_batch(config)
    ledger = gateway.ledger.dump_state()
    archives = list(registry.context_refs)

    with pytest.raises(AgentFailure) as exc:
        await gateway.invoke(messages, registry.schemas(), "1:r")

    assert exc.value.error.code == "BUDGET_EXCEEDED"
    assert not gateway.transport.requests and gateway.ledger.dump_state() == ledger
    assert registry.context_refs == archives


@pytest.mark.parametrize("tamper", ["reference", "body"])
async def test_first_batch_does_not_reuse_unbound_or_changed_source_feedback(settings, tamper):
    _, gateway, registry, messages, _ = first_batch(settings)
    payload = json.loads(messages[-1].content)
    if tamper == "reference":
        payload["artifact_refs"][0]["sha256"] = "0" * 64
    else:
        payload["documents"][0]["sha256"] = "0" * 64
    messages[-1] = messages[-1].model_copy(
        update={"content": json.dumps(payload, ensure_ascii=False)}
    )
    canonical = messages_to_dict(messages)
    artifacts = original_artifacts(registry)
    ledger = gateway.ledger.dump_state()
    archives = list(registry.context_refs)

    with pytest.raises(AgentFailure) as exc:
        await gateway.invoke(messages, registry.schemas(), "1:r")

    assert exc.value.error.code in {"EVIDENCE_INVALID", "BUDGET_EXCEEDED"}
    assert not gateway.transport.requests and gateway.ledger.dump_state() == ledger
    assert messages_to_dict(messages) == canonical and original_artifacts(registry) == artifacts
    assert registry.context_refs == archives


async def test_equal_text_from_a_different_source_cannot_borrow_preview_identity(settings):
    _, gateway, registry, messages, _ = first_batch(settings)
    original_ref = registry.refs[-1]
    artifact = registry.store.get(original_ref).model_copy(deep=True)
    document = artifact.documents.documents[0]
    document.document_id = "public-other-source"
    document.source = "fixture://public-context/independent-source"
    document.citation.source_id = text_hash("independent public source")
    document.citation.document_id = text_hash("independent public document")
    changed_ref = registry.store.put(artifact)
    registry.refs[-1] = changed_ref
    payload = json.loads(messages[-1].content)
    payload["artifact_refs"] = [changed_ref.model_dump()]
    payload["documents"][0] = document.model_dump()
    messages[-1] = messages[-1].model_copy(
        update={"content": json.dumps(payload, ensure_ascii=False)}
    )
    canonical = messages_to_dict(messages)
    artifacts = original_artifacts(registry)
    ledger = gateway.ledger.dump_state()
    archives = list(registry.context_refs)

    with pytest.raises(AgentFailure) as exc:
        await gateway.invoke(messages, registry.schemas(), "1:r")

    assert exc.value.error.code == "BUDGET_EXCEEDED"
    assert not gateway.transport.requests and gateway.ledger.dump_state() == ledger
    assert messages_to_dict(messages) == canonical and original_artifacts(registry) == artifacts
    assert registry.context_refs == archives


async def test_first_batch_real_l0_preview_preserves_source_refs_after_expansion(settings):
    manager, gateway, registry, messages, content = first_batch(
        settings, short_body=True, preview=True
    )
    canonical = messages_to_dict(messages)
    artifacts = original_artifacts(registry)
    originals = [json.loads(m.content) for m in messages if m.type == "tool"]
    assert all(payload["model_view"] == "L0" for payload in originals)
    assert all("source_ref" in d for payload in originals for d in payload["documents"])

    await gateway.invoke(messages, registry.schemas(), "1:r")

    view = gateway.transport.requests[0]
    assert "\n".join(str(m.content) for m in view).count(content["shared"]) == 1
    expanded = expanded_tool_payloads(view)
    assert len(expanded) == 2 and len(closed_batches(view)) == 1
    for original, restored in zip(originals, expanded, strict=True):
        assert {key: restored[key] for key in original} == original
        assert [d["source_ref"] for d in restored["documents"]] == [
            d["source_ref"] for d in original["documents"]
        ]
    assert messages_to_dict(messages) == canonical and original_artifacts(registry) == artifacts
    assert manager.stats[-1].summary_calls == 0 and not gateway.ledger.pending


@pytest.mark.parametrize("failure", ["capacity", "put"])
async def test_first_batch_archive_failure_prevents_model_dispatch(settings, monkeypatch, failure):
    _, gateway, registry, messages, _ = first_batch(settings)
    if failure == "capacity":
        for i in range(94):
            registry.store.put(
                Artifact(
                    run_id=registry.envelope.run_id,
                    task_id="public_quota_control",
                    plan_version=1,
                    kind="analysis",
                    source="fixture/public-quota-control",
                    values={"public_marker": str(i)},
                )
            )
    canonical = messages_to_dict(messages)
    artifacts = original_artifacts(registry)
    ledger = gateway.ledger.dump_state()
    archives = list(registry.context_refs)
    original_put = registry.store.put
    attempted = []

    def archive_put(artifact):
        if artifact.kind == "context":
            attempted.append(artifact.kind)
            if failure == "put":
                raise AgentFailure("EVIDENCE_LIMIT", "Public archive write failure control")
        return original_put(artifact)

    monkeypatch.setattr(registry.store, "put", archive_put)
    with pytest.raises(AgentFailure) as exc:
        await gateway.invoke(messages, registry.schemas(), "1:r")

    assert exc.value.error.code == "EVIDENCE_LIMIT" and attempted == ["context"]
    assert not gateway.transport.requests and gateway.ledger.dump_state() == ledger
    assert messages_to_dict(messages) == canonical and original_artifacts(registry) == artifacts
    assert registry.context_refs == archives


async def test_first_batch_unknown_usage_keeps_full_reservation_charge(settings):
    manager, gateway, registry, messages, _ = first_batch(settings)
    gateway.transport = ModelDouble(unknown=True)
    before_root = gateway.ledger.snapshot()
    before_child = gateway.ledger.snapshot("1:r")
    canonical = messages_to_dict(messages)
    artifacts = original_artifacts(registry)

    await gateway.invoke(messages, registry.schemas(), "1:r")

    assert len(gateway.transport.requests) == 1
    sent = measure_context(
        gateway.transport.requests[0], registry.schemas(), manager.limits.output_tokens
    )[1]
    reservation = sent.estimated_input_tokens + sent.output_reserved_tokens
    assert gateway.ledger.snapshot().total_tokens == before_root.total_tokens + reservation
    assert gateway.ledger.snapshot("1:r").total_tokens == before_child.total_tokens + reservation
    assert gateway.ledger.snapshot().reported_tokens == before_root.reported_tokens
    assert gateway.ledger.snapshot("1:r").reported_tokens == before_child.reported_tokens
    assert not gateway.ledger.snapshot().usage_complete
    assert not gateway.ledger.snapshot("1:r").usage_complete and not gateway.ledger.pending
    assert messages_to_dict(messages) == canonical and original_artifacts(registry) == artifacts


async def test_first_batch_peer_reservation_after_prepare_still_blocks_final_dispatch(
    settings, monkeypatch
):
    manager, gateway, registry, messages, _ = first_batch(settings)
    gateway.ledger.fork("peer", BudgetLimits(calls=1, tokens=18000))
    original = manager.prepare
    after_race = {}
    canonical = messages_to_dict(messages)
    artifacts = original_artifacts(registry)

    async def race(*args, **kwargs):
        prepared = await original(*args, **kwargs)
        sent = measure_context(prepared.messages, registry.schemas(), manager.limits.output_tokens)[
            1
        ]
        cost = sent.estimated_input_tokens + sent.output_reserved_tokens
        available = gateway.ledger.remaining("1:r")[1]
        assert cost <= available and prepared.reservation is None
        peer_ticket = gateway.ledger.reserve_batch("peer", [(0, available - cost + 1)])[0]
        after_race["ticket"] = peer_ticket
        after_race["ledger"] = gateway.ledger.dump_state()
        return prepared

    monkeypatch.setattr(manager, "prepare", race)
    with pytest.raises(AgentFailure) as exc:
        await gateway.invoke(messages, registry.schemas(), "1:r")

    assert exc.value.error.code == "BUDGET_EXCEEDED" and not gateway.transport.requests
    assert gateway.ledger.dump_state() == after_race["ledger"]
    assert after_race["ticket"] in gateway.ledger.pending
    assert messages_to_dict(messages) == canonical and original_artifacts(registry) == artifacts
