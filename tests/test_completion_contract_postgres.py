"""New synthetic Dev: actual PG/MCP/BGE/Report/Collector/frozen scorer, no Provider."""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from reporting_fixtures import host_scope, metric_fixture

from datapilot.datasets.contracts import DatasetScope
from datapilot.datasets.repository import DatasetRepository
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact, BudgetLimits, TaskEnvelope, TaskSpec
from datapilot.orchestration.rag_completion import retrieval_goal
from datapilot.orchestration.runtime import ArtifactStore, text_hash
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import RagScope, Target
from datapilot.rag.mcp import rag_session
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService, make_pin
from datapilot.reporting.contracts import CitationPolicy, CitationSource, confirm_finite_scope
from datapilot.semantics.contracts import MetricRequest
from evaluation.p7_v3_current.completion_admission import check_retrieval_expectation
from evaluation.p7_v3_current.holdout_contracts import HoldoutAnswer, HoldoutCase
from evaluation.p7_v3_current.holdout_scoring import score

OUT = None
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("reporting_output")]

# Expected states are fixed independently of the Runtime output, before any run.
CONTROLS = [
    ("full", "complete", "completed", True),
    ("full_sources", "complete", "completed", True),
    ("missing_fact", "complete", "partial", True),
    ("combined", "complete", "partial", True),
    ("partial_receipt", "insufficient", "partial", True),
    ("legacy_receipt", "insufficient", "unavailable", False),
    ("missing_source", "insufficient", "partial", True),
    ("empty", "unavailable", "unavailable", True),
]


@pytest.fixture(scope="module")
def completion_sources(portable_pg, tmp_path_factory):
    folder = tmp_path_factory.mktemp("completion-independent-sources")
    documents = {
        "tickets.md": "合成工单管理规则：工单档案每周归档；归档后由值班员核对编号。",
        "rota.md": "合成工单归档交接规则：工单档案每周归档后，换班时双方核对交接清单。",
    }
    paths = []
    for name, text in documents.items():
        path = folder / name
        path.write_text(text + "\n", encoding="utf-8")
        paths.append(path)
    owner = "completion-dev-" + uuid4().hex[:16]
    rag = RagScope(owner=owner, allow_saas=True)
    ingest = IngestionService(os.environ["DATAPILOT_RAG_INGEST_DATABASE_URL"], LocalEmbedding())
    try:
        manifest, version, reused, _ = ingest.ingest(
            Target(corpus_id=str(uuid4()), owner=owner), paths, scope=rag, reviewed=True
        )
        assert not reused
    finally:
        ingest.close()
    rag.corpora = [make_pin(manifest, version)]
    binding = {
        "scope": rag.model_dump(mode="json"),
        "manifest": manifest.model_dump(mode="json"),
        "metric": None,
    }
    return portable_pg, binding, documents


class CompletionDecisions:
    """Only scripted choices; retrieved text and verification remain real."""

    def __init__(self, query, outcome, top_k):
        from report_recovery_probe import ReportDecisions

        self.base = ReportDecisions(query)
        self.outcome, self.top_k = outcome, top_k

    async def respond(self, messages, tools):
        reply = await self.base.respond(messages, tools)
        observations = [json.loads(m.content) for m in messages if m.type == "tool"]
        search = next((o for o in observations if "document_count" in o), None)
        if (
            search
            and search["document_count"]
            and not any("context_refs" in o for o in observations)
        ):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "bounded_read",
                        "name": "read_context",
                        "args": {
                            "artifact_id": search["artifact_refs"][0]["artifact_id"],
                            "document_id": search["documents"][0]["document_id"],
                        },
                    }
                ],
                usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )
        for call in reply.tool_calls:
            if call["name"] == "search_documents":
                call["args"]["top_k"] = self.top_k
            if call["name"] == "submit_rag_result":
                failed = any(
                    o.get("error", {}).get("code") == "EVIDENCE_INSUFFICIENT" for o in observations
                )
                call["args"]["outcome"] = "insufficient" if failed else self.outcome
        return reply


@pytest.mark.parametrize("name,outcome,business,strict", CONTROLS)
def test_native_completion_to_signed_score(
    completion_sources, name, outcome, business, strict, monkeypatch
):
    settings, binding, documents = completion_sources
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from p7_business_runtime import collect
    from p7_business_scoring import authenticated, sign_collection

    question = "说明工单档案每周归档和核对编号的规则，保留真实来源引用。"
    facts = [("weekly_archive", "tickets.md", "工单档案每周归档")]
    if name not in {"full", "full_sources"}:
        facts.append(("restore_time", None, None))
    if name == "full_sources":
        facts.append(("handover_check", "rota.md", "换班时双方核对交接清单"))
    if name == "empty":
        facts = [("restore_time", None, None)]
    authored = {"id": name, "question": question, "documents": documents, "facts": facts}
    rag, scope = host_scope(authored, binding)
    dataset_pins = {}
    metric_gold = []
    if name == "combined":
        metric_folder = OUT / "combined-metric-source"
        metric_folder.mkdir()
        metric = metric_fixture(os.environ, metric_folder, scope.owner)
        scope.datasets = DatasetScope.model_validate_json(json.dumps(metric["scope"]))
        scope.metrics = [MetricRequest.model_validate_json(json.dumps(metric["request"]))]
        scope.question = "计算已支付账单收入，并" + question
        scope.document_goal.metric_goals = [scope.metrics[0].goal_id]
        scope.document_goal.independent_facts = True
        rag.datasets = scope.datasets.model_copy(deep=True)
        repo = DatasetRepository(
            settings.upload_reader_database_url.get_secret_value(), scope.datasets
        )
        try:
            schema = repo.schema(scope.metrics[0].dataset_id)
        finally:
            repo.close()
        dataset_pins["public-synthetic"] = {
            "schema": schema.model_dump(mode="json"),
            "semantics": metric["semantic"],
            "metrics": [metric["metric"]],
        }
        metric_gold = [
            {
                "goal_id": scope.metrics[0].goal_id,
                "disposition": "verified",
                "value": "637.45",
                "unit": "CNY",
            }
        ]
    if name == "empty":
        rag.min_score = 1.0  # Explicit threshold-rejection control, not a recall-quality claim.
    scope.rag_query_policy = "original-first-v1"
    if name != "legacy_receipt":
        scope.partial_evidence_policy = "partial-facts-v1"
    sources = binding["manifest"]["sources"][
        : 2 if name in {"missing_source", "full_sources"} else 1
    ]
    # Ingest preserves input path order; select by source name, not incidental DB ordering.
    if name not in {"missing_source", "full_sources"}:
        sources = [s for s in sources if s["name"] == "tickets.md"] or [
            next(s for s in binding["manifest"]["sources"] if s["name"] == "tickets.md")
        ]
    scope.citation_policy = CitationPolicy(
        goal_sha256=text_hash(scope.question),
        required_sources=[
            CitationSource(
                corpus_id=rag.corpora[0].corpus_id,
                index_version=rag.corpora[0].index_version,
                source_id=s["source_id"],
                document_id=s["document_id"],
                version=s["version"],
                source_sha256=s["text_sha256"],
            )
            for s in sources
        ],
    )
    scope = confirm_finite_scope(
        scope, rag, confirmation_ref="new-public-synthetic-completion-matrix:" + name
    )
    lane_id = "xsrc" if name == "combined" else "rag"
    cid = f"g2-bh-{lane_id}-{[c[0] for c in CONTROLS].index(name) + 1:03}"
    task = HoldoutCase.model_validate_json(
        json.dumps(
            {
                "case_id": cid,
                "lane": "sql_rag" if name == "combined" else "rag_only",
                "objective": "Independent public synthetic Dev control",
                **scope.model_dump(
                    mode="json",
                    include={
                        "owner",
                        "question",
                        "datasets",
                        "metrics",
                        "document_goal",
                        "causal_requested",
                    },
                ),
                "rag_scope": rag.model_dump(mode="json"),
                "report_scope": scope.model_dump(mode="json"),
            }
        )
    )
    known = (
        scope.document_goal.required_facts[0] if name not in {"empty", "legacy_receipt"} else None
    )
    gold = HoldoutAnswer.model_validate_json(
        json.dumps(
            {
                "case_id": cid,
                "business_completion": business,
                "host_decision": "review_then_run",
                "metrics": metric_gold,
                "refusal_conditions": [],
                "causal_claim_must_remain_unverified": False,
                "retrieval_expected": "complete"
                if name in {"partial_receipt", "legacy_receipt"}
                else outcome,
                "minimum_cited_sources": 2 if name == "full_sources" else 1 if known else 0,
                "missing_fact_ids": ["restore_time"]
                if name not in {"full", "full_sources"}
                else [],
                "document_missing_codes": ["matching_document_or_metric_evidence_missing"],
                "retrieval": {
                    "disposition": outcome,
                    "relevant_document_ids": [s["document_id"] for s in sources],
                    "facts": [
                        {
                            "document_id": known.citation.document_id,
                            "version": known.citation.version,
                            "start": known.citation.start,
                            "end": known.citation.end,
                            "literal": known.quotation,
                        }
                    ]
                    if known
                    else [],
                },
            }
        )
    )
    run_id = str(uuid4())
    folder = OUT / name
    folder.mkdir()

    async def admission():
        async with rag_session(settings, rag, goal=scope.document_goal.question) as retrieval:
            result = await retrieval.search(question, 1 if name == "missing_source" else 3)
            store = ArtifactStore("public-completion-admission")
            ref = store.put(
                Artifact(
                    run_id=store.run_id,
                    task_id="documents",
                    plan_version=1,
                    kind="documents",
                    source="real-mcp-dev-admission",
                    documents=result,
                )
            )
            env = TaskEnvelope(
                run_id=store.run_id,
                parent_id=store.run_id,
                plan_version=1,
                task=TaskSpec(task_id="documents", worker="rag", instruction=question),
                allowed_tools=["search_documents", "submit_rag_result"],
                budget=BudgetLimits(),
            )
            return check_retrieval_expectation(
                env,
                store,
                [ref],
                retrieval,
                retrieval_goal(scope.document_goal.question, retrieval, scope),
                gold.retrieval_expected,
            )

    assert run_async(admission()) == gold.retrieval_expected
    (folder / "expected-before-run.json").write_text(
        json.dumps(
            {
                "case": task.model_dump(mode="json"),
                "gold": gold.model_dump(mode="json"),
                "strict": strict,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    first = run_async(
        run_durable(
            settings,
            run_id,
            scope.question,
            owner=scope.owner,
            require_review=True,
            report_scope=scope,
            rag_scope=rag,
            transport=CompletionDecisions(
                question,
                "complete" if name == "missing_source" else outcome,
                1 if name == "missing_source" else 3,
            ),
        )
    )
    assert first["status"] == "awaiting_review"
    run_async(
        run_durable(
            settings,
            run_id,
            owner=scope.owner,
            resume=True,
            approve=True,
            report_scope=scope,
            rag_scope=rag,
            transport=CompletionDecisions(
                question,
                "complete" if name == "missing_source" else outcome,
                1 if name == "missing_source" else 3,
            ),
        )
    )
    payload = run_async(
        collect(
            {"case_id": cid, "run_id": run_id, "question_sha256": digest(scope.question)},
            settings,
            scope,
            rag,
        )
    )
    key = b"public-synthetic-completion-signing-key"
    signed = sign_collection(payload, key)
    assert authenticated(signed, key) == payload
    pins = {
        "datasets": dataset_pins,
        "corpora": {
            "public": {
                "manifest": binding["manifest"],
                "index_version": rag.corpora[0].index_version,
            }
        },
    }
    observed = score(task, gold, signed, key, pins)
    (folder / "signed-collection.json").write_text(
        json.dumps(signed, ensure_ascii=False), encoding="utf-8"
    )
    (folder / "score.json").write_text(json.dumps(observed, ensure_ascii=False), encoding="utf-8")
    assert (
        payload["model_mode"] == "fake"
        and payload["actual_provider_cost_status"] == "not_applicable_fake"
    )
    assert payload["snapshot"]["unknown"] is False
    assert payload["snapshot"]["report"]["business_completion"]["status"] == business
    receipt = payload["snapshot"]["state"]["results"]["1:documents"]["rag_completion"]
    assert receipt["submission"]["outcome"] == outcome
    assert observed["strict_correct"] is strict
    assert not observed["safety_violation"]
    if name == "combined":
        assert observed["numeric"] == [
            {"goal_id": "revenue", "correct": True, "expected": "verified"}
        ]
    if known:
        assert any(c.get("documents") for c in payload["snapshot"]["report"]["claims"])
