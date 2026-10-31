"""Bounded projections on existing Host/Message contracts, never model tools."""

import json

from datapilot.orchestration.rag_completion import retrieval_goal
from datapilot.orchestration.runtime import text_hash
from datapilot.rag.contracts import RagScope
from datapilot.rag.mcp import rag_session
from datapilot.reporting.contracts import (
    CitationPolicy,
    CitationSource,
    ReportScope,
    confirm_finite_scope,
)
from datapilot.web.chat_contracts import GoalDataset, GoalSource, ReviewDocument, ReviewView
from datapilot.web.store import deny


async def proposal(product, request, payload, selection):
    """Resolve immutable source metadata through real MCP before user review.

    No search, Agent, business calculation or model decision runs here. Qwen readiness
    uses the existing explicit lifecycle, without changing its timeout or profile.
    """
    scope = ReportScope.model_validate_json(json.dumps(payload["report_scope"]))
    rag = RagScope.model_validate_json(json.dumps(payload["rag_scope"]))
    if len(scope.question) > 512 or scope.document_goal.question != scope.question:
        deny("GOAL_INPUT_LIMIT", "请将完整文档问题限定在512字符内，不会截断原目标后确认")
    sources = []
    async with rag_session(product.settings, rag, goal=scope.document_goal.question) as tools:
        for corpus_id, manifest in tools.manifests.items():
            pin = next(p for p in rag.corpora if p.corpus_id == corpus_id)
            for source in manifest.sources:
                if source.document_id in pin.document_ids:
                    sources.append(
                        GoalSource(
                            corpus_id=corpus_id,
                            index_version=pin.index_version,
                            source_id=source.source_id,
                            document_id=source.document_id,
                            version=source.version,
                            source_sha256=source.text_sha256,
                            name=source.name,
                        )
                    )
    if not sources or len(sources) > 8:
        deny("GOAL_SOURCE_QUOTA", "本合同须选择1至8份授权原件，请缩小文档范围")
    ids = set(selection.required_source_ids)
    if ids - {s.source_id for s in sources}:
        deny("WEB_SCOPE", "必需来源不在当前授权集合")
    for source in sources:
        source.required = not ids or source.source_id in ids
    scope.citation_policy = CitationPolicy(
        goal_sha256=text_hash(scope.question),
        required_sources=[
            CitationSource(**{k: getattr(s, k) for k in CitationSource.model_fields})
            for s in sources
            if s.required
        ],
    )
    scope.rag_query_policy = "original-first-v1"
    scope.partial_evidence_policy = "partial-facts-v1"
    payload = {**payload, "report_scope": scope.model_dump(mode="json")}
    definitions, metric_names, datasets = [], [], []
    for binding in scope.datasets.bindings:
        record = product.store.dataset(binding.dataset_id, binding.version)
        schema = record["schema"]
        datasets.append(
            GoalDataset(
                dataset_id=binding.dataset_id,
                version=binding.version,
                name=schema["name"],
                source_sha256=schema["source_sha256"],
            )
        )
    for metric in request.metrics:
        record = product.store.dataset(metric.dataset_id, metric.dataset_version)
        metric_names.append(record["schema"]["name"])
        definitions.append(
            next(
                m
                for m in record["metrics"]
                if (m["metric_id"], m["metric_version"], m["semantic_version"])
                == (metric.metric_id, metric.metric_version, metric.semantic_version)
            )
        )
    review = ReviewView(
        request=request,
        definitions=definitions,
        dataset_names=metric_names,
        document_scope=[
            ReviewDocument(corpus_id=c.corpus_id, index_version=c.index_version)
            for c in rag.corpora
        ],
        model_mode=product.settings.llm_mode,
        max_model_calls=product.settings.max_model_calls,
        max_tokens=product.settings.max_total_tokens,
    )
    goal = retrieval_goal(scope.document_goal.question)
    unresolved = (
        [goal.get("unsupported_reason", "unsupported_requirement")]
        if goal["unsupported_requirements"]
        else []
    )
    return {
        "payload": payload,
        "review": review.model_dump(mode="json"),
        "datasets": [d.model_dump(mode="json") for d in datasets],
        "sources": [s.model_dump(mode="json") for s in sources],
        "unresolved": unresolved,
        "can_confirm": not unresolved,
        "limitations": [
            "仅核验本合同列出的有限目标与必需来源，不证明知识库或材料集合无遗漏",
            "用户确认范围不等于事实已验证；数值须P3 verified，文档须来源与事实校验",
            "相关政策仅作背景，不证明因果；有未解决前提时请修改或拒绝合同",
            "确认后仍需原Journal执行审批；原工具、预算与unknown规则继续生效",
        ],
    }


def base_payload(snapshot):
    """Remove only host-added finite-contract policy to compare current original grants."""
    value = json.loads(json.dumps(snapshot["payload"]))
    scope = ReportScope.model_validate_json(json.dumps(value["report_scope"]))
    scope.citation_policy = None
    scope.rag_query_policy = "legacy"
    scope.partial_evidence_policy = "legacy"
    scope.goal_scope_attestation = None
    value["report_scope"] = scope.model_dump(mode="json")
    return value


def bind_payload(snapshot, event):
    # The event ID is generated by the API and committed with this exact outbox Run.
    value = json.loads(json.dumps(snapshot["payload"]))
    scope = ReportScope.model_validate_json(json.dumps(value["report_scope"]))
    rag = RagScope.model_validate_json(json.dumps(value["rag_scope"]))
    scope = confirm_finite_scope(scope, rag, confirmation_ref="web-goal:" + event["event_id"])
    value["report_scope"] = scope.model_dump(mode="json")
    value["goal_confirmation"] = {
        k: event[k]
        for k in (
            "event_id",
            "conversation_id",
            "message_id",
            "version",
            "contract_sha256",
            "actor_session_hash",
            "confirmed_at",
            "expires_at",
        )
    }
    return value
