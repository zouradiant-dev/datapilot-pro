"""Explicit nonpaid public Dev experiment; no historical Holdout is executed."""

import argparse
import json
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/p7/citation-partial-dev-v1"
sys.path.insert(0, str(ROOT / "evaluation/p7_v3"))
from candidate import citation_policy, project  # noqa: E402
from v3_common import clean_settings, infrastructure, write_new  # noqa: E402

from datapilot.contracts import AgentFailure  # noqa: E402
from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest  # noqa: E402
from datapilot.ingestion.common import digest  # noqa: E402
from datapilot.ingestion.confirmation import confirm_schema  # noqa: E402
from datapilot.ingestion.contracts import ParseOptions  # noqa: E402
from datapilot.ingestion.parser import parse_file  # noqa: E402
from datapilot.ingestion.profiling import propose_schema  # noqa: E402
from datapilot.ingestion.service import IngestionService as DatasetIngest  # noqa: E402
from datapilot.orchestration.contracts import (  # noqa: E402
    Artifact,
    BudgetLimits,  # noqa: E402
    RagSubmission,
    TaskEnvelope,
    TaskSpec,
)
from datapilot.orchestration.runtime import ArtifactStore  # noqa: E402
from datapilot.persistence.session import run_async  # noqa: E402
from datapilot.rag.contracts import ChunkCitation, RagScope, Target  # noqa: E402
from datapilot.rag.mcp import rag_session  # noqa: E402
from datapilot.rag.models import LocalEmbedding  # noqa: E402
from datapilot.rag.storage import IngestionService, Repository, make_pin, sql  # noqa: E402
from datapilot.reporting.contracts import DocumentFact, DocumentGoal, ReportScope  # noqa: E402
from datapilot.reporting.service import report_session  # noqa: E402
from datapilot.semantics.contracts import MetricDraft, MetricRequest, MetricWindow, SemanticDraft  # noqa: E402
from datapilot.semantics.registry import RegistryStore  # noqa: E402

OWNER = "citation-partial-public-dev-v1"


def environment():
    values = infrastructure(ROOT / "artifacts/p7/unified-regression/private/environment.json")
    os.environ.update(values)
    settings = clean_settings(values)
    assert settings.llm_mode == "fake" and settings.api_key is None
    return values, settings


def cases():
    return json.loads((Path(__file__).parent / "cases.json").read_bytes())["cases"]


def metric_fixture(values):
    """New toy data and explicit synthetic host definitions, not production approval."""
    folder = OUT / "assets/cp07"
    path = folder / "invoices.csv"
    path.write_text(
        "invoice_id,amount_cents,invoice_date,payment_status,currency\n"
        "cp-i01,63745,2025-10-08,paid,CNY\n"
        "cp-i02,1199,2025-10-09,unpaid,CNY\n",
        encoding="utf-8",
    )
    parsed = parse_file(path, options=ParseOptions(header="present"))
    confirmation = confirm_schema(parsed, propose_schema(parsed), reviewed=True)
    ingest = DatasetIngest(
        values["DATAPILOT_INGEST_DATABASE_URL"], storage_dir=OUT / "private/uploads"
    )
    registry = RegistryStore(values["DATAPILOT_REGISTRY_DATABASE_URL"])
    try:
        imported = ingest.import_file(path, confirmation, ImportRequest(name=OWNER))
        from datapilot.datasets.repository import DatasetRepository

        scope = DatasetScope(
            bindings=[DatasetBinding(dataset_id=imported.dataset_id, version=imported.version)]
        )
        reader = DatasetRepository(values["DATAPILOT_UPLOAD_READER_DATABASE_URL"], scope)
        try:
            schema = reader.schema(imported.dataset_id)
        finally:
            reader.close()
        table = schema.tables[0]
        semantic = registry.confirm_semantics(
            SemanticDraft.model_validate_json(
                json.dumps(
                    {
                        "dataset_id": schema.dataset_id,
                        "dataset_version": schema.version,
                        "entities": [
                            {
                                "entity": "invoices",
                                "table_id": table.table_id,
                                "fields": {
                                    "record_id": "invoice_id",
                                    "amount": "amount_cents",
                                    "invoice_date": "invoice_date",
                                    "payment_status": "payment_status",
                                    "currency": "currency",
                                },
                                "grain": ["invoice_id"],
                                "amount_storage": "minor",
                                "coverage_start": "2025-10-01",
                                "coverage_end_exclusive": "2025-11-01",
                            }
                        ],
                    }
                )
            ),
            reviewed=True,
        )
        definition = registry.confirm_metric(
            MetricDraft(
                dataset_id=schema.dataset_id,
                dataset_version=schema.version,
                semantic_version=semantic.semantic_version,
                metric_id="paid_invoice_revenue",
            ),
            reviewed=True,
        )
        request = MetricRequest(
            goal_id="revenue",
            dataset_id=schema.dataset_id,
            dataset_version=schema.version,
            semantic_version=semantic.semantic_version,
            metric_version=definition.metric_version,
            metric_id="paid_invoice_revenue",
            window=MetricWindow(start=date(2025, 10, 1), end_exclusive=date(2025, 11, 1)),
        )
        return {
            "scope": scope.model_dump(mode="json"),
            "request": request.model_dump(mode="json"),
            "semantic": semantic.model_dump(mode="json"),
            "metric": definition.model_dump(mode="json"),
            "gold_decimal": "637.45",
            "review_basis": (
                "Synthetic trusted-host fixture only; not independent human review "
                "or production definition approval"
            ),
        }
    finally:
        registry.close()
        ingest.close()


def prepare():
    assert not (OUT / "bindings.json").exists(), "Do not reingest existing Dev"
    values, _ = environment()
    spec = json.loads((Path(__file__).parent / "cases.json").read_bytes())
    write_new(OUT / "dev-spec-before-observation.json", spec)
    embedding = LocalEmbedding()
    bindings = {}
    for case in cases():
        folder = OUT / "assets" / case["id"]
        folder.mkdir(parents=True, exist_ok=False)
        paths = []
        for name, text in case["documents"].items():
            path = folder / name
            path.write_text(text + "\n", encoding="utf-8")
            paths.append(path)
        datasets = DatasetScope()
        metric = None
        if case.get("metric"):
            metric = metric_fixture(values)
            datasets = DatasetScope.model_validate_json(json.dumps(metric["scope"]))
        scope = RagScope(owner=OWNER, allow_saas=not bool(metric), datasets=datasets)
        target = Target(
            corpus_id=str(uuid5(NAMESPACE_URL, OWNER + case["id"])),
            owner=OWNER,
            dataset_id=datasets.bindings[0].dataset_id if metric else None,
            dataset_version=datasets.bindings[0].version if metric else None,
        )
        ingest = IngestionService(values["DATAPILOT_RAG_INGEST_DATABASE_URL"], embedding)
        try:
            old = None
            if case.get("old_text"):
                paths[0].write_text(case["old_text"] + "\n", encoding="utf-8")
                om, ov, _, _ = ingest.ingest(target, paths, scope=scope, reviewed=True)
                old = {
                    "manifest": om.model_dump(mode="json"),
                    "pin": make_pin(om, ov).model_dump(mode="json"),
                }
                paths[0].write_text(case["documents"][paths[0].name] + "\n", encoding="utf-8")
            manifest, version, _, usage = ingest.ingest(target, paths, scope=scope, reviewed=True)
        finally:
            ingest.close()
        scope.corpora = [make_pin(manifest, version)]
        bindings[case["id"]] = {
            "scope": scope.model_dump(mode="json"),
            "manifest": manifest.model_dump(mode="json"),
            "old": old,
            "metric": metric,
            "embedding_usage": usage.model_dump(mode="json"),
        }
    write_new(OUT / "bindings.json", {"spec_sha256": digest(spec), "bindings": bindings})
    print("Prepared 12 new public Dev scopes; no old corpus ingested")


def host_scope(case, binding):
    rag = RagScope.model_validate_json(json.dumps(binding["scope"]))
    facts = []
    for fact_id, name, quote in case["facts"]:
        proof = {}
        if name:
            source = next(s for s in binding["manifest"]["sources"] if s["name"] == name)
            assert len(source["chunks"]) == 1 and quote in case["documents"][name]
            citation = ChunkCitation(
                **source["chunks"][0],
                corpus_id=rag.corpora[0].corpus_id,
                index_version=rag.corpora[0].index_version,
                source_id=source["source_id"],
                document_id=source["document_id"],
                version=source["version"],
                source_sha256=source["text_sha256"],
                model_revision=binding["manifest"]["model"]["revision"],
                chunker_sha256=digest(binding["manifest"]["chunker"]),
                score=0.0,
            )
            proof = {
                "citation": citation,
                "quotation": quote,
                "confirmation_ref": "public-synthetic-host-fixture-not-human-approval:"
                + case["id"],
            }
        facts.append(
            DocumentFact(
                fact_id=fact_id, description="Pre-registered synthetic literal fact", **proof
            )
        )
    metrics = (
        [MetricRequest.model_validate_json(json.dumps(binding["metric"]["request"]))]
        if binding["metric"]
        else []
    )
    scope = ReportScope(
        owner=OWNER,
        question=case["question"],
        datasets=rag.datasets,
        metrics=metrics,
        causal_requested=case.get("causal", False),
        document_goal=DocumentGoal(
            goal_id="documents",
            question=case["question"],
            metric_goals=[r.goal_id for r in metrics],
            purpose="facts",
            required_facts=facts,
        ),
    )
    return rag, scope


def source_ids(case, binding):
    names = {s["name"]: s["source_id"] for s in binding["manifest"]["sources"]}
    return {names.get(n, "missing:" + n) for n in case["required"]}


def pre_threshold(values, scope, embedding, query):
    """Dev-only scoped SELECT; no body/vector is returned to a model or public Trace."""
    repository = Repository(values["DATAPILOT_RAG_READER_DATABASE_URL"], scope)
    try:
        repository.manifests()
        vectors, _ = embedding.encode([query], query=True)
        pin = scope.corpora[0]
        with repository.read() as conn:
            rows = (
                sql(
                    conn,
                    "SELECT document_id,chunk_id,1-(embedding OPERATOR(public.<=>) "
                    "CAST(:vector AS public.vector)) AS score FROM rag.chunks "
                    "WHERE corpus_id=:c AND index_version=:v "
                    "AND document_id=ANY(CAST(:docs AS text[])) "
                    "ORDER BY embedding OPERATOR(public.<=>) "
                    "CAST(:vector AS public.vector),chunk_id LIMIT 5",
                    vector=json.dumps(vectors[0].tolist()),
                    c=pin.corpus_id,
                    v=pin.index_version,
                    docs=pin.document_ids,
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]
    finally:
        repository.close()


async def observe():
    values, settings = environment()
    data = json.loads((OUT / "bindings.json").read_bytes())
    assert data["spec_sha256"] == digest(
        json.loads((Path(__file__).parent / "cases.json").read_bytes())
    )
    embedding = LocalEmbedding()
    outputs, trials = [], []
    progress = OUT / "observation-r2"
    progress.mkdir(exist_ok=False)
    for case in cases():
        binding = data["bindings"][case["id"]]
        rag, scope = host_scope(case, binding)
        async with rag_session(settings, rag, goal=case["question"]) as retrieval:
            result = await retrieval.search(case["question"], 5)
            store = ArtifactStore("dev-" + case["id"])
            ref = store.put(
                Artifact(
                    run_id=store.run_id,
                    task_id="documents",
                    plan_version=1,
                    kind="documents",
                    source="new-public-dev-real-mcp",
                    documents=result,
                )
            )
            pairs = [(ref, store.get(ref))]
            envelope = TaskEnvelope(
                run_id=store.run_id,
                plan_version=1,
                task=TaskSpec(task_id="documents", worker="rag", instruction=case["question"]),
                allowed_tools=["search_documents", "submit_rag_result"],
                budget=BudgetLimits(),
                parent_id=store.run_id,
            )
            outcome = case["outcome"] if result.documents else "unavailable"
            submission = RagSubmission(artifact_ids=[ref.artifact_id], outcome=outcome)
            async with report_session(settings, scope, scope.question, OWNER) as service:
                metric = await service.compute("revenue") if scope.metrics else None
                metric_pairs = []
                if metric:
                    mref = store.put(
                        Artifact(
                            run_id=store.run_id,
                            task_id="revenue",
                            plan_version=1,
                            kind="metric",
                            source="original-p3-six-layer",
                            metric=metric,
                        )
                    )
                    metric_pairs = [(mref, store.get(mref))]
                    assert Decimal(metric.value.value) == Decimal("637.45")
                    assert metric.value.unit == "CNY"
                statuses = {"documents": "succeeded" if outcome == "complete" else "unavailable"}
                if metric:
                    statuses["revenue"] = "succeeded"
                baseline = service.build(
                    (pairs if outcome == "complete" else []) + metric_pairs,
                    retrieval,
                    source_statuses=statuses,
                )
                failure = None
                try:
                    if case.get("deny"):
                        narrowed = rag.model_copy(deep=True)
                        narrowed.corpora[0].document_ids = [
                            s["document_id"]
                            for s in binding["manifest"]["sources"]
                            if s["name"] != case["deny"]
                        ]
                        async with rag_session(settings, narrowed, goal=case["question"]):
                            raise AssertionError("Partial document index unexpectedly accepted")
                    if case.get("old_text"):
                        old_scope = rag.model_copy(deep=True)
                        old_scope.corpora = [
                            type(rag.corpora[0]).model_validate_json(
                                json.dumps(binding["old"]["pin"])
                            )
                        ]
                        async with rag_session(
                            settings, old_scope, goal=case["question"]
                        ) as old_tools:
                            stale = await old_tools.search(case["question"], 5)
                        assert stale.documents
                        mixed = result.model_copy(deep=True)
                        mixed.documents = [*result.documents, stale.documents[0]][:5]
                        retrieval.validate_result(mixed)
                        raise AssertionError("Stale index escaped original verifier")
                    candidate = project(
                        service,
                        pairs,
                        retrieval,
                        envelope,
                        store,
                        submission,
                        source_ids(case, binding),
                        metric=metric,
                    )
                except AgentFailure as exc:
                    failure = exc.error.code
                    candidate = None
                published = {d.citation.source_id for d in result.documents}
                supplementary = {
                    s["source_id"]
                    for s in binding["manifest"]["sources"]
                    if s["name"] == case.get("supplement")
                }
                outputs.append(
                    {
                        "case_id": case["id"],
                        "baseline": baseline.model_dump(mode="json"),
                        "candidate": candidate.model_dump(mode="json") if candidate else None,
                        "candidate_status": candidate.status if candidate else "blocked",
                        "error": failure,
                        "actual_submission": submission.model_dump(mode="json"),
                        "artifacts": [
                            artifact.model_dump(mode="json") for _, artifact in pairs + metric_pairs
                        ],
                        "refs": [r.model_dump(mode="json") for r, _ in pairs + metric_pairs],
                        "scope": scope.model_dump(mode="json"),
                        "rag_scope": rag.model_dump(mode="json"),
                        "required_sources": sorted(source_ids(case, binding)),
                        "policy_required_only": citation_policy(
                            source_ids(case, binding), published
                        ),
                        "policy_supplement": citation_policy(
                            source_ids(case, binding),
                            published,
                            supplementary,
                            allow_supplements=True,
                        ),
                    }
                )
                write_new(progress / (case["id"] + ".json"), outputs[-1])
                print(
                    case["id"],
                    "baseline=" + baseline.business_completion.status,
                    "candidate=" + outputs[-1]["candidate_status"],
                    flush=True,
                )
        strategies = {
            "scripted_proxy": [case["english"], case["topic"] + " policy requirements"],
            "original_first": [case["question"]],
            "original_plus_same_language": [case["question"], case["rewrite"]],
            "mixed_diagnostic": [case["topic"] + " " + case["english"]],
        }
        relevant = {
            s["document_id"]
            for s in binding["manifest"]["sources"]
            if s["name"] in case["required"]
        }
        for name, queries in strategies.items():
            observed, calls = set(), []
            async with rag_session(settings, rag, goal=case["question"]) as retrieval:
                for query in queries:
                    if len(calls) >= 2:
                        raise AssertionError("Search budget exceeded")
                    found = await retrieval.search(query, 5)
                    before = pre_threshold(values, rag, embedding, query)
                    ids = {d.citation.document_id for d in found.documents}
                    calls.append(
                        {
                            "query": query,
                            "result": found.model_dump(mode="json"),
                            "pre_threshold": before,
                        }
                    )
                    observed |= ids
                    if name == "original_plus_same_language" and found.documents:
                        break
            trials.append(
                {
                    "case_id": case["id"],
                    "strategy": name,
                    "calls": calls,
                    "relevant_documents": sorted(relevant),
                    "observed_documents": sorted(observed),
                    "full_required": source_ids(case, binding)
                    <= {
                        s["source_id"]
                        for s in binding["manifest"]["sources"]
                        if s["document_id"] in observed
                    },
                }
            )
            write_new(progress / (case["id"] + "-" + name + ".json"), trials[-1])
    write_new(OUT / "observations.json", outputs)
    write_new(OUT / "query-trials.json", trials)
    print("Observed 12 real PG/MCP Dev scenarios and 48 scripted query trials; paid calls=0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "observe"))
    action = parser.parse_args().action
    if action == "prepare":
        prepare()
    else:
        run_async(observe())
