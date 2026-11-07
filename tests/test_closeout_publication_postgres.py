"""Public Dev: real PG/MCP/BGE/P3/report/collector, scripted choices, no Provider.

Only a separately initialized isolated test database is permitted. No historical
question, Gold, Scope or source is read by these controls.
"""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from reporting_fixtures import host_scope, metric_fixture, validate_environment
from reporting_fixtures import portable_pg as base_portable_pg
from sqlalchemy.engine import make_url

from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetScope
from datapilot.datasets.repository import DatasetRepository
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact, BudgetLimits, TaskEnvelope, TaskSpec
from datapilot.orchestration.rag_completion import retrieval_goal
from datapilot.orchestration.runtime import ArtifactStore, text_hash
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import RagScope, SourceGoal, Target
from datapilot.rag.mcp import rag_session
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService, make_pin
from datapilot.reporting.contracts import CitationPolicy, CitationSource
from datapilot.reporting.service import report_session
from datapilot.semantics.contracts import MetricRequest
from evaluation.p7_v3_current.completion_admission import check_retrieval_expectation
from evaluation.p7_v3_current.holdout_contracts import HoldoutAnswer, HoldoutCase
from evaluation.p7_v3_current.partial_evidence_scope import confirm_document_evidence
from evaluation.p7_v3_current.profile_scoring import (
    BudgetProfile,
    ordinary_failure_may_continue_profiled,
    score_with_profile,
)
from evaluation.p7_v3_current.publication_admission import check_publication_expectation
from evaluation.p7_v3_current.source_goal_scoring import score

OUT = None
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("reporting_output")]
MODES = ["independent_same", "independent_cross", "dependent_same", "dependent_cross"]


@pytest.fixture(scope="session")
def portable_pg():
    if os.environ.get("DATAPILOT_RUN_DB_TESTS") != "1":
        pytest.skip("Real PostgreSQL integration requires DATAPILOT_RUN_DB_TESTS=1")
    settings = validate_environment(os.environ)
    target = make_url(settings.runtime_database_url.get_secret_value())
    assert (target.port or 5432) not in {55450, 55453, 55454}
    yield from base_portable_pg.__wrapped__()


class Decisions:
    """Public scripted choices only; SQL, documents and verification are real."""

    def __init__(self, queries):
        from report_recovery_probe import ReportDecisions

        self.base = ReportDecisions(queries[0])
        self.queries = queries

    async def respond(self, messages, tools):
        if messages[0].content.startswith("REPORT_PLAN_JSON"):
            return await self.base.respond(messages, tools)
        observed = [json.loads(m.content) for m in messages if m.type == "tool"]
        searches = [row for row in observed if "document_count" in row]
        if len(searches) < len(self.queries):
            name = "search_documents"
            args = {"query": self.queries[len(searches)], "top_k": 3}
        else:
            name = "submit_rag_result"
            args = {
                "artifact_ids": list(
                    dict.fromkeys(
                        ref["artifact_id"] for row in searches for ref in row["artifact_refs"]
                    )
                ),
                "outcome": "complete",
            }
        return AIMessage(
            content="",
            tool_calls=[{"id": f"public_choice_{len(observed)}", "name": name, "args": args}],
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


@pytest.mark.parametrize("mode", MODES)
def test_native_publication_contract_to_signed_score(portable_pg, mode, monkeypatch):
    settings = portable_pg.model_copy(update={"max_total_tokens": 36000})
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from p7_business_runtime import collect
    from p7_business_scoring import authenticated, sign_collection

    folder = OUT / mode
    folder.mkdir()
    owner = "public-pub-" + uuid4().hex[:16]
    metric_dir = folder / "metric"
    metric_dir.mkdir()
    metric = metric_fixture(os.environ, metric_dir, owner)
    doc_dir = folder / "document-catalog"
    doc_dir.mkdir()
    catalog = metric_fixture(os.environ, doc_dir, owner + "-catalog")
    datasets = DatasetScope.model_validate_json(
        json.dumps({"bindings": metric["scope"]["bindings"] + catalog["scope"]["bindings"]})
    )
    different = mode.endswith("cross")
    independent = mode.startswith("independent")
    doc_dataset = catalog if different else metric
    texts = {
        "archive.md": "公开合成工单条款：工单档案每周归档，归档后由值班员核对编号。",
        "handover.md": "公开合成工单条款：换班时双方核对交接清单，清单由值班员保存。",
    }
    paths = []
    for name, body in texts.items():
        path = folder / name
        path.write_text(body + "\n", encoding="utf-8")
        paths.append(path)
    rag = RagScope(owner=owner, datasets=datasets)
    ingest = IngestionService(os.environ["DATAPILOT_RAG_INGEST_DATABASE_URL"], LocalEmbedding())
    try:
        manifest, version, reused, _ = ingest.ingest(
            Target(
                corpus_id=str(uuid4()),
                owner=owner,
                dataset_id=doc_dataset["request"]["dataset_id"],
                dataset_version=1,
            ),
            paths,
            scope=rag,
            reviewed=True,
        )
        assert not reused
    finally:
        ingest.close()
    rag.corpora = [make_pin(manifest, version)]
    question = "核验已确认的已支付账单收入；独立引述归档和交接条款，不能据此确认因果。"
    authored = {
        "id": "public_" + mode,
        "question": question,
        "causal": True,
        "documents": texts,
        "facts": [
            ("weekly_archive", "archive.md", "工单档案每周归档"),
            ("handover_check", "handover.md", "换班时双方核对交接清单"),
        ],
    }
    binding = {
        "scope": rag.model_dump(mode="json"),
        "manifest": manifest.model_dump(mode="json"),
        "metric": metric,
    }
    rag, scope = host_scope(authored, binding)
    scope.document_goal.question = "分别独立引述工单档案归档和换班核对清单条款，保留因果未验证。"
    scope.document_goal.purpose = "facts" if independent else "conclusion"
    scope.document_goal.independent_facts = independent
    scope.document_goal.evidence_only = independent
    sources = [next(s for s in manifest.sources if s.name == name) for name in texts]
    components = ["工单档案每周归档的安排", "换班时核对交接清单的安排"]
    scope.document_goal.source_goals = [
        SourceGoal(
            corpus_id=manifest.target.corpus_id,
            index_version=version,
            document_id=source.document_id,
            question=query,
        )
        for source, query in zip(sources, components, strict=True)
    ]
    scope.citation_policy = CitationPolicy(
        goal_sha256=text_hash(question),
        required_sources=[
            CitationSource(
                corpus_id=manifest.target.corpus_id,
                index_version=version,
                source_id=s.source_id,
                document_id=s.document_id,
                version=s.version,
                source_sha256=s.text_sha256,
            )
            for s in sources
        ],
    )
    scope = confirm_document_evidence(
        scope, rag, confirmation_ref="public-publication-full-chain:" + mode
    )
    request = MetricRequest.model_validate_json(json.dumps(metric["request"]))

    async def native_admission():
        async with report_session(settings, scope, question, owner) as service:
            async with rag_session(
                settings,
                rag,
                goal=scope.document_goal.question,
                source_goals=scope.document_goal.source_goals,
            ) as retrieval:
                store = ArtifactStore("public-native-publication")
                bridge = await service.compute(request.goal_id)
                metric_ref = store.put(
                    Artifact(
                        run_id=store.run_id,
                        task_id=request.goal_id,
                        plan_version=1,
                        kind="metric",
                        source="real-PG-MCP-public-Dev",
                        metric=bridge,
                    )
                )
                refs = []
                for query in components:
                    found = await retrieval.search(query, 3)
                    refs.append(
                        store.put(
                            Artifact(
                                run_id=store.run_id,
                                task_id="documents",
                                plan_version=1,
                                kind="documents",
                                source="real-RAG-MCP-public-Dev",
                                documents=found,
                            )
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
                assert (
                    check_retrieval_expectation(
                        env,
                        store,
                        refs,
                        retrieval,
                        retrieval_goal(scope.document_goal.question, retrieval, scope),
                        "complete",
                    )
                    == "complete"
                )
                pairs = [(ref, store.get(ref)) for ref in [metric_ref, *refs]]
                kwargs = {
                    "source_statuses": {request.goal_id: "succeeded", "documents": "succeeded"},
                    "expected_status": "partial",
                    "expected_verified_goals": {request.goal_id},
                    "expected_evidence_goals": {"documents"} if independent else set(),
                    "expected_unconfirmed_claims": {"causal_conclusion_not_verified"},
                }
                if mode == "dependent_cross":
                    with pytest.raises(AgentFailure, match="metric Dataset/version"):
                        check_publication_expectation(service, pairs, retrieval, **kwargs)
                elif mode == "dependent_same":
                    with pytest.raises(ValueError, match="required reviewed literal fact"):
                        check_publication_expectation(service, pairs, retrieval, **kwargs)
                else:
                    report = check_publication_expectation(service, pairs, retrieval, **kwargs)
                    assert report.business_completion.satisfied_evidence_goals == ["documents"]

    run_async(native_admission())
    cid = f"g2-bh-xsrc-{MODES.index(mode) + 1:03}"
    case = HoldoutCase.model_validate_json(
        json.dumps(
            {
                "case_id": cid,
                "lane": "sql_rag",
                "objective": "Independent public publication-role Dev",
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
                "report_scope": scope.model_dump(mode="json"),
                "rag_scope": rag.model_dump(mode="json"),
            }
        )
    )
    gold = HoldoutAnswer.model_validate_json(
        json.dumps(
            {
                "case_id": cid,
                "business_completion": "partial",
                "host_decision": "review_then_run",
                "metrics": [
                    {
                        "goal_id": request.goal_id,
                        "disposition": "verified",
                        "value": "637.45",
                        "unit": "CNY",
                    }
                ],
                "refusal_conditions": [],
                "causal_claim_must_remain_unverified": True,
                "retrieval_expected": "complete",
                "minimum_cited_sources": 2,
                "missing_fact_ids": [],
                "document_missing_codes": [],
            }
        )
    )
    run_id = str(uuid4())
    transport = Decisions(components)
    first = run_async(
        run_durable(
            settings,
            run_id,
            question,
            owner=owner,
            require_review=True,
            report_scope=scope,
            rag_scope=rag,
            transport=transport,
        )
    )
    assert first["status"] == "awaiting_review"
    run_async(
        run_durable(
            settings,
            run_id,
            owner=owner,
            resume=True,
            approve=True,
            report_scope=scope,
            rag_scope=rag,
            transport=transport,
        )
    )
    payload = run_async(
        collect(
            {"case_id": cid, "run_id": run_id, "question_sha256": digest(question)},
            settings,
            scope,
            rag,
        )
    )
    repo = DatasetRepository(settings.upload_reader_database_url.get_secret_value(), datasets)
    try:
        schema = repo.schema(request.dataset_id)
    finally:
        repo.close()
    pins = {
        "datasets": {
            "public": {
                "schema": schema.model_dump(mode="json"),
                "semantics": metric["semantic"],
                "metrics": [metric["metric"]],
            }
        },
        "corpora": {
            "public": {"manifest": manifest.model_dump(mode="json"), "index_version": version}
        },
    }
    key = b"public-closeout-publication-control-signing-key"
    signed = sign_collection(payload, key)
    assert authenticated(signed, key) == payload
    profile = BudgetProfile(root_tokens=36000, worker_tokens=36000)
    result = score_with_profile(
        case, gold, signed, key, pins, profile=profile, score_original=score
    )
    assert result["budget_profile_audit"]["valid"] is True
    assert result["original_18000_score"]["strict_correct"] is independent
    assert ordinary_failure_may_continue_profiled(
        result, signed, key, expected_profile=profile
    ) is not (different and not independent)
    for name, body in [("signed-collection.json", signed), ("score.json", result)]:
        (folder / name).write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    assert (
        payload["model_mode"] == "fake"
        and payload["actual_provider_cost_status"] == "not_applicable_fake"
    )
    assert payload["snapshot"]["unknown"] is False
    assert payload["snapshot"]["usage"]["usage_complete"] is True
    assert result["strict_correct"] is independent
    assert not result.get("safety_violation", False)
    if independent:
        report = payload["snapshot"]["report"]
        assert report["business_completion"]["status"] == "partial"
        assert report["business_completion"]["satisfied_evidence_goals"] == ["documents"]
        assert "documents" not in report["business_completion"]["verified_goals"]
        assert result["numeric"] == [
            {"goal_id": request.goal_id, "correct": True, "expected": "verified"}
        ]
    elif different:
        assert payload["snapshot"]["report"] is None
        assert payload["snapshot"]["state"]["error"]["code"] == "REPORT_EVIDENCE_INVALID"
