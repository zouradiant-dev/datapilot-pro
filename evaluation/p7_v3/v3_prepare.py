"""Append-only synthetic materialization and mechanical authoring; never calls an LLM."""

import argparse
import copy
import json
from collections import Counter
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import NAMESPACE_URL, uuid5

from v3_common import (
    BASE,
    OWNER,
    ROOT,
    Answer,
    Case,
    infrastructure,
    parent_freeze,
    write_new,
)
from v3_oracle import ASOF, WINDOWS, answer, query
from v3_sources import COMBINED, COMBINED_DOCUMENT_GOALS, RAG, SQL, TEXTS, variants, write_sources

from datapilot.data.semantic_demo import mapping_draft
from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest
from datapilot.datasets.repository import DatasetRepository
from datapilot.ingestion.common import digest
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService
from datapilot.persistence.session import run_async
from datapilot.rag.contracts import ChunkCitation, RagScope, Target
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService as DocumentIngestion
from datapilot.rag.storage import make_pin
from datapilot.reporting.contracts import DocumentFact, DocumentGoal
from datapilot.semantics.contracts import MetricDraft, MetricRequest, SemanticDraft
from datapilot.semantics.registry import RegistryStore


def materialize(values):
    if (BASE / "bindings.json").exists():
        raise ValueError("Existing bindings retained; do not rematerialize")
    source = BASE / "sources"
    write_sources(source)
    result = {
        "datasets": {},
        "corpora": {},
        "seed": 730213,
        "review_basis": (
            "Explicit owner authorization for synthetic evaluat"
            "ion preparation only; AI technical review, not ind"
            "ependent human signature"
        ),
    }
    ingest = IngestionService(
        values["DATAPILOT_INGEST_DATABASE_URL"], storage_dir=BASE / "private/snapshots"
    )
    registry = RegistryStore(values["DATAPILOT_REGISTRY_DATABASE_URL"])
    try:
        for alias in [*variants(), "csv_payments"]:
            path = source / ("payments.csv" if alias == "csv_payments" else alias + ".xlsx")
            parsed = parse_file(path, options=ParseOptions(header="present"))
            confirmation = confirm_schema(parsed, propose_schema(parsed), reviewed=True)
            imported = ingest.import_file(
                path, confirmation, ImportRequest(name="p7-chengyue-v3-" + alias)
            )
            scope = DatasetScope(
                bindings=[DatasetBinding(dataset_id=imported.dataset_id, version=imported.version)]
            )
            repository = DatasetRepository(values["DATAPILOT_UPLOAD_READER_DATABASE_URL"], scope)
            try:
                schema = repository.schema(imported.dataset_id)
            finally:
                repository.close()
            row = {
                "schema": schema.model_dump(mode="json"),
                "scope": scope.model_dump(mode="json"),
                "semantics": None,
                "metrics": [],
            }
            if alias != "csv_payments":
                draft = mapping_draft(schema).model_dump(mode="json")
                for entity in draft["entities"]:
                    entity.update(coverage_start="2031-01-01", coverage_end_exclusive="2033-01-01")
                    if alias == "unconfirmed_unit" and entity["entity"] == "invoices":
                        entity["amount_storage"] = None
                    if alias == "major" and entity["entity"] == "invoices":
                        entity["amount_storage"] = "major"
                    if alias == "incomplete_history" and entity["entity"] == "subscriptions":
                        entity["history_complete"] = False
                semantic = registry.confirm_semantics(
                    SemanticDraft.model_validate_json(json.dumps(draft)), reviewed=True
                )
                row["semantics"] = semantic.model_dump(mode="json")
                for kind, extra in [
                    ("paid_invoice_revenue", {}),
                    ("paid_invoice_revenue", {"currency": "EUR"}),
                    ("usage", {"feature": "export_batch"}),
                    ("usage", {"feature": "webhook_delivery"}),
                    ("usage", {}),
                    ("customer_churn", {}),
                    ("subscription_churn", {}),
                    ("active_subscriptions", {}),
                    ("mrr", {}),
                ]:
                    metric = registry.confirm_metric(
                        MetricDraft(
                            dataset_id=schema.dataset_id,
                            dataset_version=schema.version,
                            semantic_version=semantic.semantic_version,
                            metric_id=kind,
                            **extra,
                        ),
                        reviewed=True,
                    )
                    row["metrics"].append(metric.model_dump(mode="json"))
            result["datasets"][alias] = row
            write_new(BASE / "private/materialization" / (alias + ".json"), row)
            print("materialized dataset " + alias, flush=True)
    finally:
        ingest.close()
        registry.close()
    master = result["datasets"]["master"]
    embedding = LocalEmbedding()
    docs = DocumentIngestion(values["DATAPILOT_RAG_INGEST_DATABASE_URL"], embedding)
    try:
        for alias, texts in TEXTS.items():
            scope = RagScope(
                owner=OWNER, datasets=DatasetScope.model_validate_json(json.dumps(master["scope"]))
            )
            corpus_alias = "retention" if alias.startswith("retention_") else alias
            target = Target(
                corpus_id=str(uuid5(NAMESPACE_URL, OWNER + ":" + corpus_alias)),
                owner=OWNER,
                dataset_id=master["schema"]["dataset_id"],
                dataset_version=1,
            )
            manifest, version, reused, usage = docs.ingest(
                target, [source / alias / name for name in texts], scope=scope, reviewed=True
            )
            scope.corpora = [make_pin(manifest, version)]
            row = {
                "scope": scope.model_dump(mode="json"),
                "manifest": manifest.model_dump(mode="json"),
                "index_version": version,
                "embedding_usage": usage.model_dump(mode="json"),
                "reused": reused,
            }
            result["corpora"][alias] = row
            write_new(BASE / "private/materialization" / ("corpus-" + alias + ".json"), row)
            print("materialized corpus " + alias, flush=True)
    finally:
        docs.close()
    write_new(BASE / "bindings.json", result)
    return result


def metric_request(spec, position, pins):
    alias, kind, version, period = spec
    ds = pins["datasets"][alias]["schema"]
    return MetricRequest.model_validate_json(
        json.dumps(
            {
                "goal_id": f"metric_{position}",
                "dataset_id": ds["dataset_id"],
                "dataset_version": ds["version"],
                "semantic_version": 1,
                "metric_id": kind,
                "metric_version": version,
                **(
                    {"as_of": ASOF[period]}
                    if kind == "active_subscriptions"
                    else {
                        "window": {"start": WINDOWS[period][0], "end_exclusive": WINDOWS[period][1]}
                    }
                ),
            }
        )
    )


def fact(group, name, literal, index, pins):
    if literal is None:
        return DocumentFact(
            fact_id=f"fact_{index}",
            description="核验原问题中的必需事实；来源没有可确认的对应原文，不得补猜",
        )
    item = pins["corpora"][group]
    manifest = item["manifest"]
    source = next(s for s in manifest["sources"] if s["name"] == name)
    text = TEXTS[group][name]
    start = text.index(literal)
    end = start + len(literal)
    span = next(s for s in source["chunks"] if s["start"] <= start and s["end"] >= end)
    citation = ChunkCitation(
        **span,
        corpus_id=manifest["target"]["corpus_id"],
        index_version=item["index_version"],
        source_id=source["source_id"],
        document_id=source["document_id"],
        version=source["version"],
        source_sha256=source["text_sha256"],
        model_revision=manifest["model"]["revision"],
        chunker_sha256=digest(manifest["chunker"]),
        score=0.0,
    )
    return DocumentFact(
        fact_id=f"fact_{index}",
        description=literal,
        citation=citation,
        quotation=literal,
        confirmation_ref="owner-authorized-synthetic-host-preparation-v3-not-human-gold-signature",
    )


def build_cases(pins):
    cases = []
    answers = []
    specs = {}
    for number in range(1, 61):
        lane = "sql_only" if number <= 20 else "rag_only" if number <= 40 else "sql_rag"
        groups = []
        requirements = []
        purpose = None
        causal = False
        tags = []
        if lane == "sql_only":
            question, metrics, completion, tags = SQL[number - 1]
        elif lane == "rag_only":
            question, groups, requirements, purpose, completion, causal = RAG[number - 21]
            metrics = []
        else:
            question, metrics, groups, requirements, purpose, completion, causal = COMBINED[
                number - 41
            ]
        case_id = f"p7-holdout-v3-{number:03}"
        requests = [metric_request(spec, i, pins) for i, spec in enumerate(metrics, 1)]
        refs = [
            {"goal_id": request.goal_id, **answer(*spec)}
            for request, spec in zip(requests, metrics, strict=True)
        ]
        selected = {alias for alias, *_ in metrics} | ({"master"} if lane != "sql_only" else set())
        datasets = DatasetScope.model_validate_json(
            json.dumps(
                {
                    "bindings": [
                        pins["datasets"][alias]["scope"]["bindings"][0]
                        for alias in sorted(selected)
                    ]
                }
            )
        )
        rag = None
        goal = None
        gold_facts = []
        host_code = None
        if lane != "sql_only":
            rag = RagScope(
                owner=OWNER,
                datasets=DatasetScope.model_validate_json(
                    json.dumps(pins["datasets"]["master"]["scope"])
                ),
                corpora=[
                    copy.deepcopy(pins["corpora"][group]["scope"]["corpora"][0]) for group in groups
                ],
            )
            verified_goals = [r["goal_id"] for r in refs if r["disposition"] == "verified"]
            goal = DocumentGoal(
                goal_id="documents",
                question=COMBINED_DOCUMENT_GOALS[number - 41] if lane == "sql_rag" else question,
                metric_goals=verified_goals or [r.goal_id for r in requests],
                purpose=purpose,
                required_facts=[
                    fact(*requirement, i, pins) for i, requirement in enumerate(requirements, 1)
                ],
            )
            for requirement in requirements:
                group, name, literal = requirement
                if literal:
                    source = next(
                        s
                        for s in pins["corpora"][group]["manifest"]["sources"]
                        if s["name"] == name
                    )
                    start = TEXTS[group][name].index(literal)
                    gold_facts.append(
                        {
                            "document_id": source["document_id"],
                            "version": source["version"],
                            "start": start,
                            "end": start + len(literal),
                            "literal": literal,
                        }
                    )
        # Exactly six pre-registered scope/version negatives, with no Runtime dispatch.
        if number == 18:
            datasets = DatasetScope()
            host_code = "REPORT_SCOPE_INVALID"
        if number == 19:
            raw = requests[0].model_dump(mode="json")
            raw["dataset_version"] = 999
            requests = [MetricRequest.model_validate_json(json.dumps(raw))]
            datasets = DatasetScope(
                bindings=[DatasetBinding(dataset_id=raw["dataset_id"], version=999)]
            )
            host_code = "VERSION_NOT_AUTHORIZED"
        if number in {39, 60}:
            rag.corpora[0].index_version = "a" * 64
            host_code = "DOCUMENT_NOT_AUTHORIZED"
        if number == 40:
            rag.corpora[0].document_ids = [
                pins["corpora"]["retention_old"]["manifest"]["sources"][0]["document_id"]
            ]
            host_code = "DOCUMENT_NOT_AUTHORIZED"
        if number == 59:
            rag.datasets = DatasetScope()
            host_code = "DOCUMENT_NOT_AUTHORIZED"
        task = Case(
            case_id=case_id,
            lane=lane,
            objective=f"chengyue_independent_objective_{number:03}",
            question=question,
            owner=OWNER,
            datasets=datasets,
            metrics=requests,
            document_goal=goal,
            rag_scope=rag,
            causal_requested=causal,
        )
        sources = [s for group in groups for s in pins["corpora"][group]["manifest"]["sources"]]
        # Relevant entities are not automatically every authorized document.
        relevant = {(group, name) for group, name, _ in requirements if group in groups}
        if not requirements and purpose == "conclusion":
            relevant = {("incident", "observation.md")}
        elif not requirements and groups == ["operations"] and "使用" in question:
            relevant = {("operations", "metering.md")}
        if relevant:
            sources = [
                s
                for group, name in sorted(relevant)
                for s in pins["corpora"][group]["manifest"]["sources"]
                if s["name"] == name
            ]
        retrieval_expected = None
        if goal and not host_code:
            from datapilot.orchestration.rag_completion import retrieval_goal

            requirements_contract = retrieval_goal(goal.question)
            count = len(
                {
                    s["source_id"]
                    for group in groups
                    for s in pins["corpora"][group]["manifest"]["sources"]
                }
            )
            retrieval_expected = (
                "unavailable"
                if not count
                else "insufficient"
                if requirements_contract["unsupported_requirements"]
                or count < requirements_contract["minimum_sources"]
                else "complete"
            )
        expected_codes = {
            r["goal_id"]: [r["reason"]] for r in refs if r["disposition"] == "unavailable"
        }
        gold = Answer(
            case_id=case_id,
            business_completion=completion,
            host_decision="confirmation_required"
            if number == 19
            else "permission_denied"
            if host_code
            else "review_then_run",
            metrics=refs,
            retrieval={
                "facts": gold_facts,
                "relevant_source_ids": [s["source_id"] for s in sources],
                "relevant_document_ids": [s["document_id"] for s in sources],
                "relevant_chunk_ids": [
                    chunk["chunk_id"]
                    for s in sources
                    for chunk in s["chunks"]
                    if not any(f["document_id"] == s["document_id"] for f in gold_facts)
                    or any(
                        f["document_id"] == s["document_id"]
                        and chunk["start"] < f["end"]
                        and chunk["end"] > f["start"]
                        for f in gold_facts
                    )
                ],
            },
            refusal_conditions=[],
            causal_claim_must_remain_unverified=causal,
            expected_codes=expected_codes,
            expected_verdicts={r["goal_id"]: r["disposition"] for r in refs},
            missing_fact_ids=[
                f"fact_{i}" for i, (_, _, literal) in enumerate(requirements, 1) if literal is None
            ],
            minimum_cited_sources=2
            if "至少两份文档" in question and completion in {"completed", "partial"}
            else 1
            if gold_facts
            else 0,
            host_code=host_code,
            tags=tags or [purpose or "summary"],
            retrieval_expected=retrieval_expected,
            document_missing_codes=["matching_document_or_metric_evidence_missing"]
            if goal and not groups
            else [],
        )
        cases.append(task)
        answers.append(gold)
        specs[case_id] = metrics
    return cases, answers, specs


async def sql_oracle(values, pins, tasks, answers, specs):
    from v3_common import clean_settings

    from datapilot.runtime.mcp_client import dataset_session

    checked = []
    # Mechanical source/Oracle validation only. No Agent, model, Gold tuning, or metric execution.
    for alias, binding in pins["datasets"].items():
        scope = DatasetScope.model_validate_json(json.dumps(binding["scope"]))
        async with dataset_session(clean_settings(values), scope) as tools:
            for task in tasks:
                gold = next(g for g in answers if g.case_id == task.case_id)
                for spec, expected in zip(specs[task.case_id], gold.metrics, strict=True):
                    if spec[0] != alias or expected.disposition != "verified" or gold.host_code:
                        continue
                    sql = query(*spec, binding["schema"])
                    result = await tools.execute(binding["schema"]["dataset_id"], sql)
                    if result.result.truncated or result.result.row_count != 1:
                        raise ValueError("Incomplete SQL Oracle")
                    row = result.result.rows[0]
                    if expected.denominator is not None:
                        n, d = map(int, row)
                        actual = (Decimal(n) / Decimal(d)).quantize(
                            Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN
                        )
                        assert (n, d) == (expected.numerator, expected.denominator)
                    else:
                        actual = Decimal(str(row[0]))
                    assert actual == Decimal(expected.value), (
                        task.case_id,
                        "Independent SQL/Decimal mismatch",
                    )
                    checked.append(
                        {
                            "case_id": task.case_id,
                            "goal_id": expected.goal_id,
                            "query_sha256": result.query_sha256,
                            "result_sha256": result.result_sha256,
                            "value": str(actual),
                            "unit": expected.unit,
                        }
                    )
        print("oracle checked " + alias, flush=True)
    return {"independent_sql_decimal_checks": checked, "database_writes": 0, "status": "passed"}


def author(values):
    parent_freeze()
    pins = json.loads((BASE / "bindings.json").read_bytes())
    tasks, answers, specs = build_cases(pins)
    assert len(tasks) == 60 and Counter(t.lane for t in tasks) == {
        "sql_only": 20,
        "rag_only": 20,
        "sql_rag": 20,
    }
    assert len({t.question for t in tasks}) == 60
    # Freeze author-derived answers BEFORE observing any product P3/model output.
    for name, rows in [("draft-inputs.jsonl.json", tasks), ("draft-gold.jsonl.json", answers)]:
        path = BASE / name
        body = [row.model_dump(mode="json") for row in rows]
        if path.exists():
            if json.loads(path.read_bytes()) != body:
                raise ValueError(
                    "Preserve existing authored answers; explicit new version required"
                )
        else:
            write_new(path, body)
    proof = run_async(sql_oracle(values, pins, tasks, answers, specs))
    write_new(BASE / "oracle-proof.json", proof)
    write_new(BASE / "author-specs.json", specs)
    print(
        json.dumps(
            {
                "cases": 60,
                "lane_counts": dict(Counter(t.lane for t in tasks)),
                "completion_counts": dict(Counter(g.business_completion for g in answers)),
                "sql_oracle_checks": len(proof["independent_sql_decimal_checks"]),
                "paid_requests": 0,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["materialize", "author"])
    args = parser.parse_args()
    values = infrastructure(ROOT / "artifacts/p7/unified-regression/private/environment.json")
    materialize(values) if args.action == "materialize" else author(values)
