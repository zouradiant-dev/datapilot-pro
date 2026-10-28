"""Trusted product host adapters. The UI and the model cannot import these services."""

import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest
from datapilot.db.management import management_url
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseLimits, ParseOptions, SchemaConfirmation
from datapilot.ingestion.parser import parse_bytes
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService
from datapilot.persistence.backend import Backend, execute
from datapilot.persistence.inspection import inspect_run
from datapilot.rag.contracts import CorpusPin, RagScope, Target
from datapilot.reporting.contracts import DocumentFact, DocumentGoal, ReportScope
from datapilot.runtime.mcp_client import dataset_session
from datapilot.semantics.registry import RegistryStore
from datapilot.web.config import private_directory
from datapilot.web.contracts import CitationView, ErrorInfo, MetricFact, ReportView, TaskView
from datapilot.web.store import deny


def safe_name(name, extensions):
    if (
        not re.fullmatch(r"[\w .-]{1,128}", name)
        or name.strip() != name
        or Path(name).suffix.lower() not in extensions
        or name.startswith(".")
        or name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL"}
        or re.match(r"^(COM|LPT)[0-9](\.|$)", name, re.I)
    ):
        deny("UPLOAD_NAME", "Use a plain supported filename without paths")
    return name


def public_schema(payload):
    value = {**payload, "schema": dict(payload["schema"])}
    value["schema"]["name"] = re.sub(r"^web_[a-f0-9]{12} ", "", value["schema"]["name"])
    value["schema"].pop("physical_schema", None)
    value["schema"]["tables"] = [
        {k: v for k, v in t.items() if k != "physical_name"} for t in payload["schema"]["tables"]
    ]
    return value


def preview(payload):
    """Profiles and schema, never original private row values."""
    p = payload["proposal"]
    tables = []
    for t in p["tables"]:
        columns = [
            {k: v for k, v in c.items() if k not in {"examples", "minimum", "maximum"}}
            for c in t["columns"]
        ]
        tables.append(
            {
                **{
                    k: v
                    for k, v in t.items()
                    if k not in {"preview_rows", "preview_source_rows", "columns"}
                },
                "columns": columns,
            }
        )
    return {
        "schema_version": "api-v1",
        "upload_id": payload["id"],
        "proposal_sha256": p["proposal_sha256"],
        "upload": p["upload"],
        "tables": tables,
        "candidate_relations": p["candidate_relations"],
        "confirmation": payload.get("confirmation"),
        "row_values_redacted": True,
    }


def report_view(run_id, report):
    facts, citations = [], []
    for claim in report.claims:
        if claim.kind == "metric":
            b = claim.metric
            facts.append(
                MetricFact(
                    goal_id=claim.goal_id,
                    request=b.request,
                    value=b.value,
                    evidence_id=b.evidence_id,
                    verification_id=b.verification.verification_id,
                    source_sha256=b.source_sha256,
                    semantic_sha256=b.context.semantic_sha256,
                    metric_sha256=b.context.metric_sha256,
                    evidence_sha256=b.evidence_sha256,
                    verification_sha256=b.verification_sha256,
                    query_sha256=b.query_sha256,
                    result_sha256=b.result_sha256,
                    verified_at=b.verified_at,
                    filters={
                        "currency": b.context.definition.currency,
                        "paid_values": b.context.definition.paid_values,
                        "churn_values": b.context.definition.churn_values,
                        "non_churn_end_values": b.context.definition.non_churn_end_values,
                        "feature": b.context.definition.feature,
                    },
                )
            )
        for doc in claim.documents:
            citations.append(
                CitationView(
                    artifact_id=doc.artifact_id,
                    citation=doc.citation.model_dump(mode="json"),
                    quotation=doc.excerpt if not report.authorization_scope.metrics else "",
                )
            )
    lines = [
        "# SaaS 可验证报告",
        "",
        "业务状态：" + report.business_completion.status,
        "文档引述仅说明来源明确记载的内容，不证明业务数值或因果。"
        if not report.authorization_scope.metrics
        else "文档背景不证明因果；原文和业务明细不传入浏览器。",
        "",
    ]
    for fact in facts:
        r = fact.request
        period = f"[{r.window.start},{r.window.end_exclusive})" if r.window else f"as_of={r.as_of}"
        lines.append(
            f"- {r.metric_id}: {fact.value.value} {fact.value.unit}; {period}; "
            f"Evidence {fact.evidence_id}; Verification {fact.verification_id}"
        )
    for c in citations:
        lines.append(
            f"- 文档引用 Chunk {c.citation.chunk_id}，"
            f"行 {c.citation.line_start}–{c.citation.line_end}（描述性背景）"
        )
    missing = [m.model_dump(mode="json") for c in report.claims for m in c.missing_requirements]
    lines += [
        "- 待补证据：" + code
        for codes in report.business_completion.missing_evidence.values()
        for code in codes
    ]
    return ReportView(
        run_id=run_id,
        authorization_sha256=report.authorization_sha256,
        execution_status=report.execution_status,
        business_completion=report.business_completion,
        facts=facts,
        citations=citations,
        charts=[
            {
                "kind": c.kind,
                "unit": c.unit,
                "points": [
                    {
                        "goal_id": p.goal_id,
                        "value": p.metric.value.value,
                        "evidence_id": p.metric.evidence_id,
                    }
                    for p in c.points
                ],
            }
            for c in report.charts
        ],
        missing_requirements=missing,
        markdown="\n".join(lines),
    )


class ProductService:
    def __init__(self, settings, store):
        self._settings, self.store, self.policy = settings, store, store.policy
        self._host_bound = False

    @property
    def settings(self):
        return self._settings

    @settings.setter
    def settings(self, value):
        if self._host_bound:
            self.store.publish_host_settings(value)
        self._settings = value

    def bind_host_settings(self):
        self.store.publish_host_settings(self.settings)
        self._host_bound = True

    def upload(self, data, name, options=None):
        safe_name(name, {".csv", ".xlsx"})
        parsed = parse_bytes(data, name, options=options or ParseOptions(), limits=ParseLimits())
        proposal = propose_schema(parsed)
        id_ = str(uuid4())
        ref = id_ + "/" + name
        path = self.policy.object_path(ref)
        private_directory(path.parent)
        path.write_bytes(data)
        p = {"id": id_, "object_ref": ref, "proposal": proposal.model_dump(mode="json")}
        self.store.put_upload(id_, p)
        return preview(p)

    def confirm(self, id_, request):
        p = self.store.upload(id_)
        from datapilot.ingestion.contracts import SchemaProposal

        proposal = SchemaProposal.model_validate_json(json.dumps(p["proposal"]))
        if proposal.proposal_sha256 != request.proposal_sha256:
            deny("SCHEMA_STALE", "Review the current schema proposal")
        path = self.policy.object_path(p["object_ref"])
        data = parse_bytes(
            path.read_bytes(), path.name, options=proposal.options, limits=proposal.limits
        )
        confirmed = confirm_schema(
            data, proposal, reviewed=request.reviewed, overrides=request.overrides
        )
        p["confirmation"] = confirmed.model_dump(mode="json")
        self.store.put_upload(id_, p)
        return preview(p)

    async def dataset(self, id_, version):
        p = self.store.dataset(id_, version)
        scope = DatasetScope(bindings=[DatasetBinding(dataset_id=id_, version=version)])
        async with dataset_session(self.settings, scope) as tools:
            schema = await tools.schema(id_)
        if schema.model_dump(mode="json") != p["schema"]:
            deny("WEB_SOURCE_CHANGED", "Authorized Dataset snapshot changed")
        return p

    async def import_upload(self, id_, request):
        p = self.store.upload(id_)
        if request.dataset_id:
            # Existing IDs must have been explicitly granted to this host first.
            if not self.store.has_dataset(request.dataset_id):
                deny()
        if not p.get("confirmation") or (
            p["confirmation"]["confirmation_sha256"] != request.confirmation_sha256
        ):
            deny("SCHEMA_CONFIRMATION_REQUIRED", "Confirm the current schema before importing")
        importer = IngestionService(
            management_url("ingest"), storage_dir=self.policy.data_dir / "sources"
        )
        try:
            result = importer.import_file(
                self.policy.object_path(p["object_ref"]),
                SchemaConfirmation.model_validate_json(json.dumps(p["confirmation"])),
                ImportRequest(
                    name="web_"
                    + hashlib.sha256(self.policy.owner.encode()).hexdigest()[:12]
                    + " "
                    + request.name,
                    dataset_id=request.dataset_id,
                ),
            )
        finally:
            importer.close()
        scope = DatasetScope(
            bindings=[DatasetBinding(dataset_id=result.dataset_id, version=result.version)]
        )
        async with dataset_session(self.settings, scope) as tools:
            self.store.grant(await tools.schema(result.dataset_id))
        return result

    async def confirm_definition(self, request, kind):
        d = request.draft
        await self.dataset(d.dataset_id, d.dataset_version)
        registry = RegistryStore(management_url("registry"))
        try:
            record = (
                registry.confirm_semantics(d, reviewed=request.reviewed)
                if kind == "semantics"
                else registry.confirm_metric(d, reviewed=request.reviewed)
            )
        finally:
            registry.close()
        self.store.definition(record, kind)
        return record

    async def documents(self, id_, version, data, name, reviewed):
        await self.dataset(id_, version)
        safe_name(name, {".txt", ".md"})
        if not reviewed or len(data) > 256 * 1024:
            deny("DOCUMENT_REVIEW_REQUIRED", "Review a supported document within 256 KiB")
        from datapilot.rag.models import LocalEmbedding
        from datapilot.rag.storage import IngestionService as RagIngestor
        from datapilot.rag.storage import make_pin

        target = Target(
            corpus_id=str(uuid4()), owner=self.policy.owner, dataset_id=id_, dataset_version=version
        )
        scope = RagScope(
            owner=self.policy.owner,
            datasets=DatasetScope(bindings=[DatasetBinding(dataset_id=id_, version=version)]),
        )
        ref = str(uuid4()) + "/" + name
        path = self.policy.object_path(ref)
        private_directory(path.parent)
        path.write_bytes(data)
        ingestor = RagIngestor(management_url("rag_ingest"), LocalEmbedding())
        try:
            manifest, ver, reused, usage = ingestor.ingest(
                target, [path], scope=scope, reviewed=True
            )
        finally:
            ingestor.close()
        pin = make_pin(manifest, ver)
        self.store.corpus(target, pin)
        return {
            "corpus_id": target.corpus_id,
            "index_version": ver,
            "reused": reused,
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "embedding_fixture": manifest.model.fixture,
            "usage": usage.model_dump() if usage else None,
        }

    async def task_payload(self, request, *, allow_unconfirmed=False):
        from datapilot.runtime.mcp_client import metric_session

        if request.documents and request.documents.purpose is None and not allow_unconfirmed:
            deny("DOCUMENT_CONFIRMATION_REQUIRED", "请先确认文档用途；不会自动推断为总结")
        bindings, sources, contexts = {}, {}, []
        for metric in request.metrics:
            p = await self.dataset(metric.dataset_id, metric.dataset_version)
            b = DatasetBinding(dataset_id=metric.dataset_id, version=metric.dataset_version)
            if metric.dataset_id in bindings and bindings[metric.dataset_id] != b:
                deny("WEB_SCOPE", "One Dataset version per run is required")
            bindings[metric.dataset_id] = b
            sources[metric.dataset_id] = p["schema"]["source_sha256"]
            if not any(
                m["metric_id"] == metric.metric_id
                and m["metric_version"] == metric.metric_version
                and m["semantic_version"] == metric.semantic_version
                for m in p["metrics"]
            ):
                deny("METRIC_CONFIRMATION_REQUIRED", "Host review of metric policy is required")
            async with metric_session(self.settings, DatasetScope(bindings=[b])) as tools:
                contexts.append((await tools.context(metric)).context_sha256)
        doc_goal, rag = None, None
        if request.documents:
            selected = []
            for id_ in request.documents.corpus_ids:
                matches = [
                    c
                    for c in self.store.corpora(corpus_id=id_)
                    if c["corpus_id"] == id_
                    and (
                        not request.metrics
                        or (c["dataset_id"], c["dataset_version"])
                        in {(b.dataset_id, b.version) for b in bindings.values()}
                    )
                ]
                if len(matches) != 1:
                    deny("WEB_SCOPE", "Choose a current host-authorized document index")
                if not request.metrics:
                    c = matches[0]
                    p = await self.dataset(c["dataset_id"], c["dataset_version"])
                    b = DatasetBinding(dataset_id=c["dataset_id"], version=c["dataset_version"])
                    if b.dataset_id in bindings and bindings[b.dataset_id] != b:
                        deny("WEB_SCOPE", "One Dataset version per run is required")
                    bindings[b.dataset_id] = b
                    sources[b.dataset_id] = p["schema"]["source_sha256"]
                selected.append(CorpusPin.model_validate(matches[0]["payload"]))
            rag = RagScope(
                owner=self.policy.owner,
                corpora=selected,
                datasets=DatasetScope(bindings=list(bindings.values())),
            )
            doc_goal = DocumentGoal(
                goal_id="documents",
                question=request.documents.question,
                metric_goals=request.documents.metric_goals,
                purpose=request.documents.purpose,
                required_facts=[
                    DocumentFact(**f.model_dump()) for f in request.documents.required_facts
                ],
            )
        report = ReportScope(
            owner=self.policy.owner,
            question=request.question,
            datasets=DatasetScope(bindings=list(bindings.values())),
            metrics=request.metrics,
            document_goal=doc_goal,
            causal_requested=request.causal_requested,
        )
        return {
            "question": request.question,
            "require_review": request.require_review,
            "report_scope": report.model_dump(mode="json"),
            "rag_scope": rag.model_dump(mode="json") if rag else None,
            "sources": sources,
            "contexts": contexts,
            "host_policy_sha256": self.store.host_settings_hash(self.settings),
            "settings": self.settings.model_dump(
                mode="json",
                exclude={
                    "api_key",
                    "reader_database_url",
                    "upload_reader_database_url",
                    "runtime_database_url",
                    "rag_reader_database_url",
                },
            ),
        }

    async def authorize_run(self, id_):
        self.store.check_host_settings(self.settings)
        row = self.store.run(id_)
        p = row["payload"]
        for b in p["report_scope"]["datasets"]["bindings"]:
            actual = await self.dataset(b["dataset_id"], b["version"])
            if actual["schema"]["source_sha256"] != p["sources"][b["dataset_id"]]:
                deny()
        # Rebuild the scope with exact current host grants, not client parameters.
        from datapilot.web.contracts import CreateTask, DocumentQuery

        rs = ReportScope.model_validate_json(json.dumps(p["report_scope"]))
        docs = (
            DocumentQuery(
                question=rs.document_goal.question,
                metric_goals=rs.document_goal.metric_goals,
                corpus_ids=[c["corpus_id"] for c in p["rag_scope"]["corpora"]],
                purpose=rs.document_goal.purpose,
                required_facts=[
                    {"fact_id": f.fact_id, "description": f.description}
                    for f in rs.document_goal.required_facts
                ],
            )
            if rs.document_goal
            else None
        )
        fresh = await self.task_payload(
            CreateTask(
                question=p["question"],
                metrics=rs.metrics,
                documents=docs,
                require_review=p["require_review"],
                causal_requested=rs.causal_requested,
            ),
            allow_unconfirmed=True,  # Historical scopes remain unconfirmed, never upgraded.
        )
        # Legacy registered runs still undergo the original P5B manifest checks.
        # Old unregistered tasks cannot execute without the new infrastructure pin.
        if "host_policy_sha256" not in p:
            fresh.pop("host_policy_sha256")
        if fresh != p:
            deny("RECOVERY_VERSION", "Host policy or confirmed scope changed")
        return row

    async def inspect(self, id_):
        row = await self.authorize_run(id_)
        p = row["payload"]
        backend = Backend(
            self.settings.runtime_database_url.get_secret_value(), id_, self.policy.owner
        )
        try:
            with backend.engine.connect() as conn:
                exists = execute(
                    conn, "SELECT 1 FROM execution.runs WHERE run_id=:run", run=id_
                ).first()
        finally:
            backend.close()
        if not exists:
            error = row["last_error"]
            status = (
                "blocked"
                if (error or {}).get("manual_action_required")
                else "cancelled"
                if row["cancel_requested"]
                else "failed"
                if error
                else "pending"
            )
            return TaskView(
                run_id=id_,
                status=status,
                usage={} if status == "cancelled" else None,
                error=ErrorInfo(**error) if error else None,
                expires_at=row["expires_at"],
                question=p["question"],
                requested_metrics=ReportScope.model_validate_json(
                    json.dumps(p["report_scope"])
                ).metrics,
            ), None
        observed = await inspect_run(
            self.settings,
            id_,
            self.policy.owner,
            p["question"],
            report_scope=ReportScope.model_validate_json(json.dumps(p["report_scope"])),
            rag_scope=RagScope.model_validate(p["rag_scope"]) if p["rag_scope"] else None,
        )
        s, report = observed["state"], observed["report"]
        status = (
            "awaiting_review"
            if observed["review"]
            else "running"
            if observed["next"]
            else "completed"
            if s.get("status") == "succeeded"
            else s.get("status", "pending")
        )
        if status in {"running", "pending"} and row["command_seq"] == row["processed_seq"]:
            status = "paused"
        error = row["last_error"]
        if error is None and s.get("error") is not None:
            original = s["error"]
            error = {
                "code": original.code,
                "message": "执行未完成；请检查模型或工具状态",
                "retryable": original.retryable,
                "manual_action_required": False,
            }
        if observed["unknown"] and row["command_seq"] == row["processed_seq"]:
            error = {
                "code": "RECOVERY_UNCERTAIN",
                "message": "外部调用结果未知；请人工对账，禁止自动重发",
                "manual_action_required": True,
            }
            status = "blocked"
        elif error:
            status = "blocked" if error["manual_action_required"] else "failed"
        if report and status == "completed":
            status = report.business_completion.status
        if (
            row["cancel_requested"]
            and status not in {"completed", "partial", "unavailable"}
            and not (error or {}).get("manual_action_required")
        ):
            status = "cancelled"
        tasks = [
            {
                "task_id": r.task_id,
                "worker": r.worker,
                "status": r.status,
                "plan_version": r.plan_version,
            }
            for r in s.get("results", {}).values()
        ]
        return TaskView(
            run_id=id_,
            status=status,
            execution_status=s.get("status"),
            business_completion=s.get("business_completion")
            or (report.business_completion if report else None),
            plan_version=s.get("plan_version"),
            steps=s.get("steps", 0),
            tasks=tasks,
            usage=observed["usage"],
            error=ErrorInfo(**error) if error else None,
            expires_at=row["expires_at"],
            report_available=report is not None
            and not error
            and s.get("status") in {"succeeded", "unavailable"},
            question=p["question"],
            requested_metrics=ReportScope.model_validate_json(
                json.dumps(p["report_scope"])
            ).metrics,
        ), report
