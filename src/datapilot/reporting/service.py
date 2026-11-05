"""Host P3 adapter and deterministic Report Agent. No free-form numeric claims."""

import re
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime

from datapilot.contracts import AgentFailure
from datapilot.db.management import management_url
from datapilot.harness.metric_verification import equal_value
from datapilot.ingestion.common import digest
from datapilot.reporting.contracts import (
    BusinessCompletion,
    ChartPoint,
    ChartSpec,
    CrossSourceReport,
    DocumentReference,
    MetricBridge,
    ReportClaim,
    ReportScope,
    source_identity,
)
from datapilot.runtime.mcp_client import metric_session
from datapilot.semantics.contracts import MissingRequirement
from datapilot.semantics.contracts import ReportClaim as P3Claim
from datapilot.semantics.registry import RegistryStore
from datapilot.semantics.service import analyze, validate_claims

TOPICS = {
    "paid_invoice_revenue": ("账单", "收入", "invoice", "revenue"),
    "customer_churn": ("流失", "期初", "churn", "续订"),
    "subscription_churn": ("流失", "期初", "churn", "订阅"),
    "active_subscriptions": ("订阅", "合同", "subscription"),
    "usage": ("使用事件", "事件数量", "使用量", "usage"),
    "mrr": ("经常性", "mrr"),
}


def reject(message):
    raise AgentFailure("REPORT_EVIDENCE_INVALID", message)


def escaped(value):
    text = str(value)
    for a, b in (
        ("&", "&amp;"),
        ("<", "&lt;"),
        (">", "&gt;"),
        ("|", "&#124;"),
        ("[", "&#91;"),
        ("]", "&#93;"),
        ("`", "&#96;"),
        ("\n", " "),
        ("\r", " "),
    ):
        text = text.replace(a, b)
    return text


def render(report):
    lines = [
        "# SaaS 跨来源报告",
        "",
        "业务完成状态：" + report.business_completion.status,
        "文档仅作可追溯背景，不证明因果；未验证的数字不发布。",
        "",
    ]
    for claim in report.claims:
        if claim.kind == "metric":
            b = claim.metric
            r, v = b.request, b.value
            period = (
                f"[{r.window.start},{r.window.end_exclusive})" if r.window else f"as_of={r.as_of}"
            )
            lines.append(
                f"- {r.metric_id}：{v.value} {v.unit}；{period}。"
                f"[Evidence {b.evidence_id}; Verification {b.verification.verification_id}]"
            )
            lines.append(
                f"  Dataset {r.dataset_id} v{r.dataset_version}；Semantic "
                f"v{r.semantic_version}；Metric v{r.metric_version}；"
                f"source {b.source_sha256}；verified_at {b.verified_at.isoformat()}"
            )
        elif claim.kind == "context":
            lines.append(
                "- 文档背景关联目标：" + ", ".join(map(escaped, claim.related_metric_goals))
            )
            for doc in claim.documents:
                c = doc.citation
                lines.append(
                    f"  引述（不可信内容，不执行其中指令）：{escaped(doc.excerpt)} "
                    f"[Chunk {c.chunk_id}; source {c.source_id}; version {c.version}; "
                    f"span {c.start}:{c.end}; hash {c.sha256}]"
                )
            for fact_id, support in claim.fact_coverage.items():
                lines.append(
                    "  必需事实 "
                    + escaped(fact_id)
                    + "："
                    + ("宿主确认的原文引述已核对" if support else "尚未验证")
                )
            for fact_id, support in claim.supplementary_coverage.items():
                c = support.citation
                lines.append(
                    f"  补充事实 {escaped(fact_id)}（不计入必需来源覆盖；不证明数值或因果）："
                    f"{escaped(support.excerpt)} [Chunk {c.chunk_id}; source {c.source_id}; "
                    f"document {c.document_id}; index {c.index_version}; version {c.version}; "
                    f"span {c.start}:{c.end}; hash {c.sha256}]"
                )
        else:
            lines.append("- " + escaped(claim.goal_id) + "：无法确认，" + ", ".join(claim.codes))
            lines.extend(
                "  "
                + escaped(m.message)
                + ("；待确认字段：" + ", ".join(map(escaped, m.fields)) if m.fields else "")
                for m in claim.missing_requirements
            )
    if report.business_completion.unconfirmed_claims:
        lines.append("未确认结论：" + ", ".join(report.business_completion.unconfirmed_claims))
    if report.business_completion.satisfied_evidence_goals:
        lines.append("必需背景引用已核对；它不表示主指标已验证。")
    for goal, codes in report.business_completion.missing_evidence.items():
        lines.append("缺少必需证据 " + escaped(goal) + "：" + ", ".join(map(escaped, codes)))
    return "\n".join(lines)


def fact_coverage(goal, documents, *, facts=None):
    """Verify host-reviewed literal support, not arbitrary natural-language truth.

    Query scores/goal vectors are observations, not immutable source identity. Authority
    still comes only from the actual retrieval's original scope and source verification.
    """
    observations = {"score", "goal_sha256", "goal_score"}
    coverage = {}
    for fact in goal.required_facts if facts is None else facts:
        support = None
        if fact.citation is not None:
            for doc in documents:
                if (
                    fact.citation.model_dump(exclude=observations)
                    == doc.citation.model_dump(exclude=observations)
                    and fact.quotation in doc.excerpt
                ):
                    support = doc.model_copy(update={"excerpt": fact.quotation}, deep=True)
                    break
        coverage[fact.fact_id] = support
    return coverage


class ReportService:
    def __init__(self, settings, scope, tools, contexts, sources, problems):
        self.settings, self.scope = settings, scope
        self.tools, self.contexts, self.sources, self.problems = tools, contexts, sources, problems
        self.requests = {r.goal_id: r for r in scope.metrics}
        self.proofs = {}

    @property
    def rag_question(self):
        return (
            self.scope.document_goal.question if self.scope.document_goal else self.scope.question
        )

    def manifest(self):
        return {
            "scope": self.scope.model_dump(mode="json"),
            "sources": self.sources,
            "contexts": {g: digest(c) if c else None for g, c in self.contexts.items()},
            "problems": self.problems,
        }

    def validate_citation_policy(self, retrieval):
        """Classifications only narrow the original MCP scope; they never grant a source."""
        policy = self.scope.citation_policy
        if policy is None:
            return
        if retrieval is None:
            reject("Citation policy requires the original RAG scope")
        pins = {p.corpus_id: p for p in retrieval.scope.corpora}
        for anchor in [
            *policy.required_sources,
            *(f.citation for f in policy.supplementary_claims),
        ]:
            pin = pins.get(anchor.corpus_id)
            manifest = retrieval.manifests.get(anchor.corpus_id)
            source = (
                next((s for s in manifest.sources if s.source_id == anchor.source_id), None)
                if manifest
                else None
            )
            if (
                pin is None
                or source is None
                or pin.index_version != anchor.index_version
                or anchor.document_id not in pin.document_ids
                or not retrieval.scope.permits(manifest.target)
                or (source.document_id, source.version, source.text_sha256)
                != (anchor.document_id, anchor.version, anchor.source_sha256)
            ):
                reject("Citation classification escaped the authorized source/version pin")

    def plan_menu(self):
        goals = [
            {
                "task_id": r.goal_id,
                "worker": "sql",
                "instruction": f"Compute confirmed {r.metric_id}; goal {r.goal_id}",
            }
            for r in self.scope.metrics
        ]
        if doc := self.scope.document_goal:
            goals.append({"task_id": doc.goal_id, "worker": "rag", "instruction": doc.question})
        return goals

    def validate_plan(self, plan):
        menu = {g["task_id"]: g for g in self.plan_menu()}
        if plan.unsupported or {t.task_id for t in plan.tasks} != {*menu, "report"}:
            raise AgentFailure("PLAN_COVERAGE", "Plan must cover only the host-approved goals")
        for task in plan.tasks:
            if task.task_id == "report":
                if task.worker != "report" or set(task.dependencies) != set(menu):
                    raise AgentFailure("PLAN_COVERAGE", "Report must depend on all required goals")
            elif task.worker != menu[task.task_id]["worker"] or task.dependencies:
                raise AgentFailure("PLAN_INVALID", "Planner cannot reassign metric capabilities")
        return plan

    async def plan(self, gateway):
        import json

        from langchain_core.messages import HumanMessage, SystemMessage

        from datapilot.orchestration.contracts import Plan

        menu = self.plan_menu()
        prompt = (
            "REPORT_PLAN_JSON: Return only a Plan JSON matching "
            + json.dumps(Plan.model_json_schema())
            + "\nUse every host goal exactly once, same task_id and worker, no dependencies "
            "on source tasks. Add one report task named report depending on every goal. "
            "Do not confirm definitions, invent goals, SQL, scripts or permissions. "
            "HOST_APPROVED_GOALS: " + json.dumps(menu, ensure_ascii=False)
        )
        reply = await gateway.invoke(
            [SystemMessage(content=prompt), HumanMessage(content=self.scope.question)], [], "root"
        )
        if reply.tool_calls or reply.invalid_tool_calls:
            raise AgentFailure("PLAN_INVALID", "Planner cannot call tools")
        return self.validate_plan(Plan.model_validate_json(reply.content))

    async def compute(self, goal_id):
        request = self.requests[goal_id]
        context = self.contexts[goal_id]
        source = self.sources[request.dataset_id]["source_sha256"]
        if context is None:
            return MetricBridge(
                request=request,
                source_sha256=source,
                verdict="unavailable",
                missing=[
                    MissingRequirement(
                        code=self.problems[goal_id].lower(),
                        message="需要在可信宿主确认映射或指标版本",
                    )
                ],
                verified_at=datetime.now(UTC),
            )
        # Registry writes are isolated host infrastructure, never a Worker or MCP tool.
        registry = RegistryStore(management_url("registry"))
        try:
            result = await analyze(self.settings, registry, [request])
        finally:
            registry.close()
        outcome = result.outcomes[0]
        tools = self.tools[request.dataset_id]
        evidence = await tools.evidence(request.dataset_id, outcome.evidence_id)
        record = await tools.verification(request.dataset_id, outcome.verification.verification_id)
        bridge = MetricBridge(
            request=request,
            source_sha256=source,
            context=context,
            evidence_id=evidence.evidence_id,
            evidence_sha256=digest(evidence),
            query_sha256=evidence.query_sha256,
            result_sha256=evidence.result_sha256,
            verification=record,
            verification_sha256=digest(record),
            verdict=record.verdict,
            value=outcome.value,
            missing=outcome.missing,
            verified_at=datetime.now(UTC),
        )
        self.proofs[evidence.evidence_id] = (evidence, record)
        self.verify_metric(bridge)
        return bridge

    async def refresh(self, artifacts):
        for artifact in artifacts:
            if bridge := artifact.metric:
                if bridge.evidence_id:
                    tools = self.tools.get(bridge.request.dataset_id)
                    if tools is None:
                        reject("Metric artifact escaped authorized dataset scope")
                    e = await tools.evidence(bridge.request.dataset_id, bridge.evidence_id)
                    if bridge.verification is None:
                        reject("Missing persisted Verification reference")
                    v = await tools.verification(
                        bridge.request.dataset_id, bridge.verification.verification_id
                    )
                    self.proofs[e.evidence_id] = (e, v)
                self.verify_metric(bridge)

    def verify_metric(self, bridge):
        bridge = MetricBridge.model_validate_json(bridge.model_dump_json())
        r = bridge.request
        if self.requests.get(r.goal_id) != r or self.contexts[r.goal_id] != bridge.context:
            reject("Metric request/confirmed definition differs from host scope")
        if self.sources[r.dataset_id]["source_sha256"] != bridge.source_sha256:
            reject("Metric source snapshot differs")
        if bridge.evidence_id is None:
            if bridge.verdict != "unavailable" or self.contexts[r.goal_id] is not None:
                reject("Missing P3 reference cannot become verified")
            if [m.code for m in bridge.missing] != [self.problems[r.goal_id].lower()]:
                reject("Unconfirmed definition reason changed")
            return
        if bridge.context is None:
            reject("P3 references require confirmed context")
        if digest(bridge.context.model_dump(mode="json", exclude={"context_sha256"})) != (
            bridge.context.context_sha256
        ):
            reject("Confirmed metric context content hash changed")
        pair = self.proofs.get(bridge.evidence_id)
        if pair is None:
            reject("P3 reference has not been revalidated through scoped MCP")
        e, v = pair
        if (
            digest(e) != bridge.evidence_sha256
            or digest(v) != bridge.verification_sha256
            or v != bridge.verification
            or v.verdict != bridge.verdict
            or e.context_sha256 != bridge.context.context_sha256
            or e.source_sha256 != bridge.source_sha256
            or e.request != r
            or e.semantic_sha256 != bridge.context.semantic_sha256
            or e.metric_sha256 != bridge.context.metric_sha256
            or e.query_sha256 != bridge.query_sha256
            or e.result_sha256 != bridge.result_sha256
        ):
            reject("P3 persisted evidence/verdict/definition hash differs")
        if bridge.verdict == "verified" and not equal_value(bridge.value, e.value):
            reject("Metric value/unit differs from persisted P3 evidence")
        validate_claims(
            [r],
            [
                P3Claim(
                    goal_id=r.goal_id,
                    kind="metric" if bridge.verdict == "verified" else "unavailable",
                    evidence_id=e.evidence_id,
                    verification_id=v.verification_id,
                    value=bridge.value,
                )
            ],
            lambda _: e,
            lambda _: v,
        )

    def build(
        self, artifacts, retrieval, *, source_statuses=None, execution_status=None, observed_at=None
    ):
        from datapilot.orchestration.rag_completion import retrieval_goal

        if not isinstance(self.scope, ReportScope) or type(self.scope.causal_requested) is not bool:
            raise AgentFailure(
                "REPORT_SCOPE_INVALID", "Host report scope requires boolean causality"
            )
        try:
            # Reject bypassed/mutated host DTOs; never accept a Worker's replacement contract.
            ReportScope.model_validate_json(self.scope.model_dump_json())
        except ValueError:
            raise AgentFailure(
                "REPORT_SCOPE_INVALID", "Invalid host document requirements"
            ) from None
        self.validate_citation_policy(retrieval)
        claims, charts, covered, missing = [], [], [], {}
        satisfied_evidence = []
        partial_facts = False
        authorization = digest(
            {
                "report_scope": self.scope.model_dump(mode="json"),
                "rag_scope_sha256": retrieval.authority_context()["rag_scope_sha256"]
                if retrieval
                else None,
            }
        )
        by_goal = {}
        for ref, artifact in artifacts:
            if (
                ref.kind != artifact.kind
                or ref.artifact_id != ref.sha256
                or digest(artifact) != ref.sha256
            ):
                reject("Artifact reference/hash differs from its source payload")
            by_goal.setdefault(artifact.task_id, []).append((ref, artifact))
        for request in self.scope.metrics:
            items = by_goal.get(request.goal_id, [])
            if len(items) > 1:
                reject("Duplicate metric goal artifact")
            item = items[0] if items else None
            bridge = item[1].metric if item else None
            if bridge:
                self.verify_metric(bridge)
            if bridge and bridge.verdict == "verified":
                claims.append(ReportClaim(goal_id=request.goal_id, kind="metric", metric=bridge))
                charts.append(
                    ChartSpec(
                        unit=bridge.value.unit,
                        authorization_sha256=authorization,
                        dataset_scope=self.scope.datasets.model_copy(deep=True),
                        owner=self.scope.owner,
                        rag_scope_sha256=(
                            retrieval.authority_context()["rag_scope_sha256"] if retrieval else None
                        ),
                        points=[ChartPoint(goal_id=request.goal_id, metric=bridge)],
                    )
                )
                covered.append(request.goal_id)
            else:
                codes = [m.code for m in bridge.missing] if bridge else ["metric_evidence_missing"]
                codes = codes or ["metric_verification_rejected"]
                missing[request.goal_id] = codes
                claims.append(
                    ReportClaim(
                        goal_id=request.goal_id,
                        kind="unavailable",
                        codes=codes,
                        missing_requirements=bridge.missing
                        if bridge and bridge.missing
                        else [
                            MissingRequirement(
                                code=codes[0],
                                message="缺少 P3 已验证指标证据，请检查映射、口径和验证记录",
                            )
                        ],
                    )
                )
        for goal in self.scope.unbound_metric_goals:
            missing[goal.goal_id] = [goal.reason]
            claims.append(
                ReportClaim(
                    goal_id=goal.goal_id,
                    kind="unavailable",
                    codes=[goal.reason],
                    missing_requirements=[
                        MissingRequirement(
                            code=goal.reason,
                            message="待确认的指标目标：" + goal.description,
                            fields=["metric_definition"]
                            if goal.reason == "definition_missing"
                            else ["p3_verified_evidence"],
                        )
                    ],
                )
            )
        if goal := self.scope.document_goal:
            if not self.scope.metrics and (
                retrieval is None
                or not retrieval.scope.corpora
                or retrieval.scope.owner != self.scope.owner
                or retrieval.scope.datasets != self.scope.datasets
            ):
                reject("Document-only report needs the original host-bound Corpus/source scope")
            docs, supplementary_docs, seen = [], [], set()
            policy = self.scope.citation_policy
            required_sources = (
                {source_identity(s) for s in policy.required_sources} if policy else None
            )
            requested_names = (
                set(re.findall(r"(?<![\w.-])([\w-]+\.(?:md|txt))(?![\w.-])", goal.question))
                if not self.scope.metrics
                else set()
            )
            selected_names = set()
            requirements = retrieval_goal(goal.question, retrieval, self.scope)
            # A source task's insufficient receipt cannot be promoted by the report.
            source_ready = (
                source_statuses is None or source_statuses.get(goal.goal_id) == "succeeded"
            )
            partial_source = (
                self.scope.partial_evidence_policy == "partial-facts-v1"
                and source_statuses is not None
                and source_statuses.get(goal.goal_id) == "unavailable"
            )
            for ref, artifact in by_goal.get(goal.goal_id, []):
                if (
                    not artifact.documents
                    or not (source_ready or partial_source)
                    or requirements["unsupported_requirements"]
                    or not requirements["completion_eligible"]
                ):
                    continue
                result = artifact.documents
                retrieval.validate_result(result)
                selected = (
                    [
                        d
                        for d in result.documents
                        if all(t in d.text for t in requirements["required_terms"])
                    ]
                    if requirements["required_terms"]
                    else retrieval.qualifying_documents(result.documents, requirements)
                )
                for doc in selected:
                    if re.search(
                        r"ignore.*instructions|system prompt|绕过.*(?:权限|验证)|"
                        r"执行.*(?:SQL|脚本)|标记.*verified",
                        doc.text,
                        re.IGNORECASE,
                    ):
                        continue  # Content is data, never an instruction or a report approval.
                    manifest = retrieval.manifests[doc.citation.corpus_id]
                    source = next(
                        s for s in manifest.sources if s.source_id == doc.citation.source_id
                    )
                    is_required = (
                        required_sources is None
                        or source_identity(doc.citation) in required_sources
                    )
                    if is_required and requested_names and source.name not in requested_names:
                        continue
                    target = manifest.target
                    if target.dataset_id and (target.dataset_id, target.dataset_version) not in {
                        (b.dataset_id, b.version) for b in self.scope.datasets.bindings
                    }:
                        reject("Document source escaped host Dataset/version")
                    for id_ in goal.metric_goals:
                        r = self.requests[id_]
                        # Independent literal facts retain their own authorized Dataset pin;
                        # they never become measurement evidence for an associated metric.
                        if (
                            not goal.independent_facts
                            and target.dataset_id
                            and (target.dataset_id, target.dataset_version)
                            != (r.dataset_id, r.dataset_version)
                        ):
                            reject("Document source does not match the metric Dataset/version")
                    identity = (doc.citation.index_version, doc.citation.chunk_id)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    if is_required:
                        selected_names.add(source.name)
                    (docs if is_required else supplementary_docs).append(
                        DocumentReference(
                            artifact_id=ref.artifact_id, citation=doc.citation, excerpt=doc.text
                        )
                    )
            metric_topics_match = goal.independent_facts or all(
                any(
                    any(term in d.excerpt.lower() for term in TOPICS[self.requests[g].metric_id])
                    for d in docs
                )
                for g in goal.metric_goals
            )
            coverage = fact_coverage(goal, docs)
            supplementary = (
                {
                    id_: proof
                    for id_, proof in fact_coverage(
                        goal, docs + supplementary_docs, facts=policy.supplementary_claims
                    ).items()
                    if proof is not None
                }
                if policy and all(g in covered for g in goal.metric_goals)
                else {}
            )
            if policy and goal.required_facts:
                # For fact goals a classified source alone is not proof: publish/count
                # only passages that actually support host-confirmed required facts.
                docs = list(
                    {
                        (p.artifact_id, p.citation.chunk_id, p.excerpt): p
                        for p in coverage.values()
                        if p is not None
                    }.values()
                )
            topics_match = (
                len({d.citation.source_id for d in docs}) >= requirements["minimum_sources"]
                and bool(docs)
                and requested_names <= selected_names
                and metric_topics_match
                and (
                    required_sources is None
                    or required_sources <= {source_identity(d.citation) for d in docs}
                )
            )
            # Only exact host-reviewed facts may survive an incomplete retrieval.
            # Related background, similarity and an accepted receipt are not fact proof.
            metric_dependencies_ready = goal.evidence_only or all(
                g in covered for g in goal.metric_goals
            )
            partial_display = (
                self.scope.partial_evidence_policy == "partial-facts-v1"
                and (source_ready or partial_source)
                and any(coverage.values())
                and metric_dependencies_ready
                and metric_topics_match
            )
            if (source_ready and topics_match and metric_dependencies_ready) or (partial_display):
                codes = [
                    "document_fact_unverified:" + id_
                    for id_, proof in coverage.items()
                    if proof is None
                ]
                if goal.purpose is None:
                    codes.append("document_goal_unconfirmed")
                elif goal.purpose == "conclusion":
                    codes.append("document_conclusion_unverified")
                if partial_source:
                    codes.append("rag_task_insufficient")
                if not topics_match:
                    codes.append("matching_document_or_metric_evidence_missing")
                if required_sources is not None and not required_sources <= {
                    source_identity(d.citation) for d in docs
                }:
                    codes.append("required_document_source_missing")
                if codes:
                    missing[goal.goal_id] = codes
                elif goal.evidence_only:
                    satisfied_evidence.append(goal.goal_id)
                else:
                    covered.append(goal.goal_id)
                partial_facts = not goal.evidence_only and (
                    any(coverage.values()) or goal.purpose == "conclusion"
                )
                claims.append(
                    ReportClaim(
                        goal_id=goal.goal_id,
                        kind="context",
                        documents=(
                            list(
                                {
                                    (p.artifact_id, p.citation.chunk_id, p.excerpt): p
                                    for p in coverage.values()
                                    if p is not None
                                }.values()
                            )
                            if partial_display and (partial_source or not topics_match)
                            else docs
                        ),
                        related_metric_goals=goal.metric_goals,
                        fact_coverage=coverage,
                        supplementary_coverage=supplementary,
                    )
                )
            else:
                missing[goal.goal_id] = [
                    "snapshot_not_attested"
                    if requirements.get("unsupported_reason") == "snapshot_not_attested"
                    else "goal_scope_not_attested"
                    if not requirements["completion_eligible"]
                    and not requirements["unsupported_requirements"]
                    else "matching_document_or_metric_evidence_missing"
                ]
                if required_sources is not None and not required_sources <= {
                    source_identity(d.citation) for d in docs
                }:
                    missing[goal.goal_id].append("required_document_source_missing")
                if policy:
                    missing[goal.goal_id].extend(
                        "document_fact_unverified:" + id_
                        for id_, proof in coverage.items()
                        if proof is None
                    )
                if (
                    goal.retain_source_context
                    and partial_source
                    and docs
                    and metric_dependencies_ready
                    and metric_topics_match
                ):
                    missing[goal.goal_id].extend(
                        "document_fact_unverified:" + id_
                        for id_, proof in coverage.items()
                        if proof is None
                    )
                    missing[goal.goal_id].append("rag_task_insufficient")
                    claims.append(
                        ReportClaim(
                            goal_id=goal.goal_id,
                            kind="context",
                            documents=docs,
                            related_metric_goals=goal.metric_goals,
                            fact_coverage=coverage,
                        )
                    )
                elif supplementary:
                    # Optional facts remain visible without satisfying any required goal.
                    claims.append(
                        ReportClaim(
                            goal_id=goal.goal_id,
                            kind="context",
                            related_metric_goals=goal.metric_goals,
                            supplementary_coverage=supplementary,
                        )
                    )
                else:
                    claims.append(
                        ReportClaim(
                            goal_id=goal.goal_id,
                            kind="unavailable",
                            codes=missing[goal.goal_id],
                            missing_requirements=[
                                MissingRequirement(
                                    code=missing[goal.goal_id][0],
                                    message="宿主未证明所要求的最新或跨来源一致快照"
                                    if "snapshot_not_attested" in missing[goal.goal_id]
                                    else "缺少满足原始问题证据要求的授权文档"
                                    if not self.scope.metrics
                                    else (
                                        "缺少满足检索要求且与指标匹配的授权文档，或关联指标尚未通过验证"
                                    ),
                                    fields=["document_source"]
                                    if not self.scope.metrics
                                    else ["document_source", "metric_evidence"],
                                )
                            ],
                        )
                    )
        required = list(self.requests) + (
            [self.scope.document_goal.goal_id] if self.scope.document_goal else []
        )
        required += [goal.goal_id for goal in self.scope.unbound_metric_goals]
        unconfirmed = ["causal_conclusion_not_verified"] if self.scope.causal_requested else []
        status = (
            "partial"
            if (covered or partial_facts) and (missing or unconfirmed)
            else ("completed" if not missing and not unconfirmed else "unavailable")
        )
        outcomes = set((source_statuses or {}).values())
        execution_status = execution_status or (
            "failed"
            if outcomes & {"failed", "blocked", "cancelled"}
            else "unavailable"
            if "unavailable" in outcomes
            else "succeeded"
        )
        if execution_status in {"failed", "cancelled"}:
            status = "blocked"
        completion = BusinessCompletion(
            status=status,
            required_goals=required,
            verified_goals=covered,
            satisfied_evidence_goals=satisfied_evidence,
            missing_evidence=missing,
            unconfirmed_claims=unconfirmed,
            limited_results_visible=bool(covered) or any(c.kind == "context" for c in claims),
        )
        document_claims = [c for c in claims if c.kind == "context"]
        for chart in charts:
            chart.document_refs = [
                d
                for c in document_claims
                if chart.points[0].goal_id in c.related_metric_goals
                for d in c.documents
            ]
        report = CrossSourceReport(
            authorization_sha256=authorization,
            authorization_scope=self.scope.model_copy(deep=True),
            rag_scope=retrieval.scope.model_copy(deep=True) if retrieval else None,
            execution_status=execution_status,
            business_completion=completion,
            claims=claims,
            charts=charts,
            verified_at=observed_at or datetime.now(UTC),
            markdown="",
        )
        report.markdown = render(report)
        return report

    def verify_report(self, report, artifacts, retrieval, *, source_statuses=None):
        report = CrossSourceReport.model_validate_json(report.model_dump_json())
        expected = self.build(
            artifacts,
            retrieval,
            source_statuses=source_statuses,
            observed_at=report.verified_at,
        )
        if report != expected:
            reject("Report/claim/chart differs from independently verified source projections")


@asynccontextmanager
async def report_session(settings, scope: ReportScope | None, question, owner):
    if scope is None:
        yield None
        return
    scope = ReportScope.model_validate_json(scope.model_dump_json())
    if scope.owner != owner or scope.question != question:
        raise AgentFailure("REPORT_SCOPE_INVALID", "Host report goal/owner does not match")
    tools, contexts, sources, problems = {}, {}, {}, {}
    async with AsyncExitStack() as stack:
        for binding in scope.datasets.bindings:
            from datapilot.datasets.contracts import DatasetBinding, DatasetScope

            tools[binding.dataset_id] = await stack.enter_async_context(
                metric_session(
                    settings,
                    DatasetScope(
                        bindings=[
                            DatasetBinding(dataset_id=binding.dataset_id, version=binding.version)
                        ]
                    ),
                )
            )
            schema = await tools[binding.dataset_id].schema(binding.dataset_id)
            sources[binding.dataset_id] = {
                "version": schema.version,
                "source_sha256": schema.source_sha256,
            }
        for request in scope.metrics:
            try:
                contexts[request.goal_id] = await tools[request.dataset_id].context(request)
            except AgentFailure as exc:
                if exc.error.code not in {"SEMANTIC_NOT_CONFIRMED", "METRIC_NOT_CONFIRMED"}:
                    raise
                contexts[request.goal_id] = None
                problems[request.goal_id] = exc.error.code
        yield ReportService(settings, scope, tools, contexts, sources, problems)
