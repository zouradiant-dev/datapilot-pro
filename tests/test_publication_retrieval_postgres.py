"""New synthetic Dev; real PG/MCP/BGE/durable receipts, no Provider or old Holdout."""

import copy
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from reporting_fixtures import host_scope

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact, BudgetLimits, TaskEnvelope, TaskSpec
from datapilot.orchestration.rag_completion import retrieval_goal
from datapilot.orchestration.runtime import ArtifactStore, text_hash
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import RagScope, SourceGoal, Target
from datapilot.rag.mcp import rag_session
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService, make_pin
from datapilot.reporting.contracts import CitationPolicy, CitationSource, UnboundMetricGoal
from evaluation.p7_v3_current.completion_admission import check_retrieval_expectation
from evaluation.p7_v3_current.holdout_contracts import HoldoutAnswer, HoldoutCase
from evaluation.p7_v3_current.partial_evidence_scope import confirm_document_evidence
from evaluation.p7_v3_current.source_goal_scoring import score

OUT = None
pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("reporting_output")]
CASES = json.loads((Path(__file__).parent / "fixtures/rag/source-goal-cases.json").read_bytes())[
    "cases"
]
CONTROLS = [
    *[(c["id"], "completed", True) for c in CASES],
    ("paraphrase", "completed", True),
    ("missing_source", "partial", False),
    ("unbound", "partial", True),
    ("unbound_insufficient", "partial", False),
    ("empty", "unavailable", True),
    ("unresolved", "partial", True),
]


@pytest.fixture(scope="module")
def native_environment(portable_pg):
    return portable_pg, LocalEmbedding()


class Decisions:
    """Scripted queries from host-reviewed input components; never fixture answers."""

    def __init__(self, queries, mode):
        from report_recovery_probe import ReportDecisions

        self.base = ReportDecisions(queries[0])
        self.queries, self.mode = queries, mode

    async def respond(self, messages, tools):
        if messages[0].content.startswith("REPORT_PLAN_JSON"):
            return await self.base.respond(messages, tools)
        observed = [json.loads(m.content) for m in messages if m.type == "tool"]
        searches = [o for o in observed if "document_count" in o]
        if len(searches) < len(self.queries):
            query = (
                self.queries[0] if self.mode == "missing_source" else self.queries[len(searches)]
            )
            name, args = (
                "search_documents",
                {"query": query, "top_k": 1 if self.mode == "missing_source" else 3},
            )
        elif (
            self.mode != "missing_source"
            and not any("context_refs" in o for o in observed)
            and any(o["document_count"] for o in searches)
        ):
            first = next(o for o in searches if o["document_count"])
            name, args = (
                "read_context",
                {
                    "artifact_id": first["artifact_refs"][0]["artifact_id"],
                    "document_id": first["documents"][0]["document_id"],
                },
            )
        else:
            insufficient = self.mode == "unbound_insufficient" or any(
                o.get("error", {}).get("code") == "EVIDENCE_INSUFFICIENT" for o in observed
            )
            outcome = (
                "unavailable"
                if not any(o["document_count"] for o in searches)
                else "insufficient"
                if insufficient
                else "complete"
            )
            name, args = (
                "submit_rag_result",
                {
                    "artifact_ids": list(
                        dict.fromkeys(
                            r["artifact_id"] for o in searches for r in o["artifact_refs"]
                        )
                    ),
                    "outcome": outcome,
                },
            )
        return AIMessage(
            content="",
            tool_calls=[{"id": f"choice_{len(observed)}", "name": name, "args": args}],
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )


class NoModel:
    async def respond(self, *_):
        raise AssertionError("Terminal restoration must not call any model")


def material(name):
    if name == "unresolved":
        return {
            "id": name,
            "question": (
                "这两份展馆规定是否足以确定统一的复核窗口？请分别引述各自的期限与优先级声明。"
            ),
            "components": [
                "展馆试点公告的复核窗口与优先级声明",
                "展馆地区细则的复核窗口与覆盖声明",
            ],
            "documents": {
                "notice.md": "合成展馆试点公告：复核窗口为九日；本公告没有声明优先级。",
                "regional.md": "合成展馆地区细则：复核窗口为十三日；本细则没有声明覆盖其他公告。",
            },
            "facts": [
                ["notice_window", "notice.md", "复核窗口为九日"],
                ["regional_window", "regional.md", "复核窗口为十三日"],
                ["priority_absent", "notice.md", "本公告没有声明优先级"],
            ],
        }
    base = copy.deepcopy(
        next(
            c for c in CASES if c["id"] == (name if name in {c["id"] for c in CASES} else "station")
        )
    )
    if name == "paraphrase":
        base["question"] = (
            "先解释气象站告警计数与重复发送的关系，再交代野外站点电池更换和传感器检查的维护安排。"
        )
    if name in {"unbound", "unbound_insufficient"}:
        base["question"] = (
            "请引述气象站的电池维护安排，并给出实际账单总额；缺少证明的部分须明确说明。"
        )
        base["components"] = base["components"][:1]
        base["facts"] = base["facts"][:1]
    if name == "empty":
        base["question"] = "请根据当前授权资料说明海底火山岩浆的黏度测量结果，并保留原文依据。"
        base["components"] = ["海底火山岩浆黏度测量记录"]
        base["facts"] = [["requested_measurement", None, None]]
    return base


@pytest.mark.parametrize("name,business,strict", CONTROLS)
def test_native_publication_and_source_components(
    native_environment, name, business, strict, monkeypatch
):
    settings, embedding = native_environment
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    from p7_business_runtime import collect
    from p7_business_scoring import authenticated, sign_collection

    row = material(name)
    folder = OUT / name
    folder.mkdir()
    assets = folder / "sources"
    assets.mkdir()
    paths = []
    for filename, text in row["documents"].items():
        p = assets / filename
        p.write_text(text + "\n", encoding="utf-8")
        paths.append(p)
    owner = "source-dev-" + uuid4().hex[:16]
    rag = RagScope(owner=owner, allow_saas=True)
    ingest = IngestionService(os.environ["DATAPILOT_RAG_INGEST_DATABASE_URL"], embedding)
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
    rag, scope = host_scope(row, binding)
    if name == "unresolved":
        scope.document_goal.purpose = "conclusion"
    required_names = list(row["documents"])[: len(row["components"])]
    sources = [next(s for s in manifest.sources if s.name == n) for n in required_names]
    scope.citation_policy = CitationPolicy(
        goal_sha256=text_hash(scope.question),
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
    scope.document_goal.source_goals = [
        SourceGoal(
            corpus_id=manifest.target.corpus_id,
            index_version=version,
            document_id=s.document_id,
            question=q,
        )
        for s, q in zip(sources, row["components"], strict=True)
    ]
    if name in {"unbound", "unbound_insufficient"}:
        scope.unbound_metric_goals = [
            UnboundMetricGoal(
                goal_id="requested_number",
                description="实际账单总额",
                reason="p3_evidence_required",
            )
        ]
    scope = confirm_document_evidence(
        scope, rag, confirmation_ref="new-public-source-components:" + name
    )
    assert scope.rag_query_policy == "source-goals-v1" and rag.min_score == 0.55
    cid = f"g2-bh-rag-{[x[0] for x in CONTROLS].index(name) + 1:03}"
    task = HoldoutCase.model_validate_json(
        json.dumps(
            {
                "case_id": cid,
                "lane": "rag_only",
                "objective": "New synthetic source-component Dev",
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
                "business_completion": "completed" if name == "missing_source" else business,
                "host_decision": "review_then_run",
                "metrics": [],
                "refusal_conditions": [],
                "causal_claim_must_remain_unverified": False,
                "minimum_cited_sources": 0 if name == "empty" else len(sources),
                "retrieval_expected": "unavailable" if name == "empty" else "complete",
                "missing_fact_ids": ["requested_measurement"] if name == "empty" else [],
                "document_missing_codes": ["matching_document_or_metric_evidence_missing"],
                "expected_codes": {"requested_number": ["p3_evidence_required"]}
                if name in {"unbound", "unbound_insufficient"}
                else {},
            }
        )
    )
    pins = {
        "datasets": {},
        "corpora": {
            "public": {"manifest": manifest.model_dump(mode="json"), "index_version": version}
        },
    }
    for filename, body in [
        (
            "expected-before-run.json",
            {
                "case": task.model_dump(mode="json"),
                "gold": gold.model_dump(mode="json"),
                "strict": strict,
                "observed_business": business,
            },
        ),
        ("pins.json", pins),
    ]:
        (folder / filename).write_text(
            json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async def admission():
        async with rag_session(
            settings,
            rag,
            goal=scope.document_goal.question,
            source_goals=scope.document_goal.source_goals,
        ) as tools:
            store = ArtifactStore("public-source-admission")
            refs = []
            for q in row["components"]:
                result = await tools.search(q, 3)
                refs.append(
                    store.put(
                        Artifact(
                            run_id=store.run_id,
                            task_id="documents",
                            plan_version=1,
                            kind="documents",
                            source="real-mcp-dev-witness",
                            documents=result,
                        )
                    )
                )
            envelope = TaskEnvelope(
                run_id=store.run_id,
                parent_id=store.run_id,
                plan_version=1,
                task=TaskSpec(task_id="documents", worker="rag", instruction=scope.question),
                allowed_tools=["search_documents", "submit_rag_result"],
                budget=BudgetLimits(),
            )
            return check_retrieval_expectation(
                envelope,
                store,
                refs,
                tools,
                retrieval_goal(scope.question, tools, scope),
                gold.retrieval_expected,
            )

    assert run_async(admission()) == gold.retrieval_expected
    run_id = str(uuid4())
    transport = Decisions(row["components"], name)
    first = run_async(
        run_durable(
            settings,
            run_id,
            scope.question,
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
    value = {"case_id": cid, "run_id": run_id, "question_sha256": digest(scope.question)}
    payload = run_async(collect(value, settings, scope, rag))
    key = b"public-source-goal-control-signing-key"
    signed = sign_collection(payload, key)
    assert authenticated(signed, key) == payload
    (folder / "signed-collection.json").write_text(
        json.dumps(signed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result = score(task, gold, signed, key, pins)
    for filename, body in [("signed-collection.json", signed), ("score.json", result)]:
        (folder / filename).write_text(
            json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    assert payload["model_mode"] == "fake" and payload["snapshot"]["unknown"] is False
    assert result["strict_correct"] is strict and not result["safety_violation"]
    report = payload["snapshot"]["report"]
    assert report["business_completion"]["status"] == business
    assert not report["charts"] and all(c.get("metric") is None for c in report["claims"])
    searches = [
        call
        for c in payload["calls"]
        if c["kind"] == "model"
        for call in c["payload"]["data"].get("tool_calls", [])
        if call["name"] == "search_documents"
    ]
    assert 1 <= len(searches) <= 2 and all(
        c["args"]["query"] in row["components"] for c in searches
    )
    if name in {"unbound", "unbound_insufficient"}:
        assert report["business_completion"]["missing_evidence"]["requested_number"] == [
            "p3_evidence_required"
        ]
        assert any(c.get("documents") for c in report["claims"])
    if name == "empty":
        text = " ".join(m["message"] for c in report["claims"] for m in c["missing_requirements"])
        assert "尚未取得" in text and "冲突" not in text and "优先级" not in text
    if name == "unresolved":
        assert "尚不足以确定" in report["markdown"]
    repeated = run_async(
        run_durable(
            settings,
            run_id,
            owner=owner,
            resume=True,
            report_scope=scope,
            rag_scope=rag,
            transport=NoModel(),
        )
    )
    assert repeated["cross_source_report"].model_dump(mode="json") == report
    if name == "station":
        changed = scope.model_copy(deep=True)
        changed.document_goal.source_goals[0].question += "及记录留存"
        changed = confirm_document_evidence(
            changed, rag, confirmation_ref="changed-public-source-goal"
        )
        with pytest.raises(AgentFailure) as error:
            run_async(
                run_durable(
                    settings,
                    run_id,
                    owner=owner,
                    resume=True,
                    report_scope=changed,
                    rag_scope=rag,
                    transport=NoModel(),
                )
            )
        assert error.value.error.code == "RECOVERY_IDENTITY"
        after = run_async(collect(value, settings, scope, rag))
        assert after["snapshot"]["usage"] == payload["snapshot"]["usage"]
        assert [call["call_key"] for call in payload["calls"]] == sorted(
            call["call_key"] for call in payload["calls"]
        )
        assert after["calls"] == payload["calls"]
    if strict and name != "empty":
        forged = copy.deepcopy(payload)
        doc = next(c for c in forged["snapshot"]["report"]["claims"] if c.get("documents"))[
            "documents"
        ][0]
        doc["citation"]["source_goal_sha256"] = "0" * 64
        bad = score(task, gold, sign_collection(forged, key), key, pins)
        assert bad["strict_correct"] is False and bad["dimensions"]["source_goal_binding"] is False
