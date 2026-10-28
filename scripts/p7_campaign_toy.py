"""Three unrelated public Toy lanes over the actual campaign adapter; never Holdout runs."""

import argparse
import json
from uuid import NAMESPACE_URL, uuid5

from openpyxl import load_workbook
from p7_business_scoring import authenticated
from p7_business_v2 import BASE
from p7_campaign import prepare_launch, run_container
from p7_gate2b import ROOT, environment, inspect, write_new
from p7_holdout_pack import CaseInput, Gold, NumericGold
from pydantic import Field

from datapilot.data.semantic_demo import mapping_draft
from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest
from datapilot.datasets.repository import DatasetRepository
from datapilot.ingestion.common import digest
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService
from datapilot.rag.contracts import RagScope, Target
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService as RagIngestion
from datapilot.rag.storage import make_pin
from datapilot.semantics.contracts import MetricDraft, MetricRequest
from datapilot.semantics.registry import RegistryStore


class ToyTask(CaseInput):
    case_id: str = Field(pattern=r"^toy-[a-z-]+$")


class ToyGold(Gold):
    case_id: str = Field(pattern=r"^toy-[a-z-]+$")


def prepare():
    inspect()
    env = environment()
    private = BASE / "private/toy"
    private.mkdir(parents=True)
    source = private / "public-saas-with-customers.xlsx"
    workbook = load_workbook(ROOT / "tests/fixtures/semantics/saas_metrics.xlsx")
    customers = sorted({row[1] for row in list(workbook["invoices"].values)[1:]})
    sheet = workbook.create_sheet("customers")
    sheet.append(["customer_id"])
    for id_ in customers:
        sheet.append([id_])
    workbook.save(source)
    workbook.close()
    parsed = parse_file(source, options=ParseOptions(header="present"))
    service = IngestionService(
        env["DATAPILOT_INGEST_DATABASE_URL"], storage_dir=private / "snapshots"
    )
    try:
        imported = service.import_file(
            source,
            confirm_schema(parsed, propose_schema(parsed), reviewed=True),
            ImportRequest(name="p7-v2-public-toy"),
        )
    finally:
        service.close()
    datasets = DatasetScope(
        bindings=[DatasetBinding(dataset_id=imported.dataset_id, version=imported.version)]
    )
    repository = DatasetRepository(env["DATAPILOT_UPLOAD_READER_DATABASE_URL"], datasets)
    registry = RegistryStore(env["DATAPILOT_REGISTRY_DATABASE_URL"])
    try:
        schema = repository.schema(imported.dataset_id)
        semantic = registry.confirm_semantics(mapping_draft(schema), reviewed=True)
        metric = registry.confirm_metric(
            MetricDraft(
                dataset_id=schema.dataset_id,
                dataset_version=1,
                semantic_version=semantic.semantic_version,
                metric_id="paid_invoice_revenue",
            ),
            reviewed=True,
        )
    finally:
        repository.close()
        registry.close()
    request = MetricRequest.model_validate_json(
        json.dumps(
            {
                "goal_id": "revenue",
                "dataset_id": schema.dataset_id,
                "dataset_version": 1,
                "semantic_version": semantic.semantic_version,
                "metric_id": "paid_invoice_revenue",
                "metric_version": metric.metric_version,
                "window": {"start": "2025-10-01", "end_exclusive": "2025-11-01"},
            }
        )
    )
    doc = ROOT / "tests/fixtures/reporting/billing.md"
    rag = RagScope(owner="p7-v2-toy", datasets=datasets)
    target = Target(
        corpus_id=str(uuid5(NAMESPACE_URL, "p7-v2-public-toy-corpus")),
        owner=rag.owner,
        dataset_id=schema.dataset_id,
        dataset_version=1,
    )
    ingestor = RagIngestion(env["DATAPILOT_RAG_INGEST_DATABASE_URL"], LocalEmbedding())
    try:
        manifest, version, _, _ = ingestor.ingest(target, [doc], scope=rag, reviewed=True)
    finally:
        ingestor.close()
    rag.corpora = [make_pin(manifest, version)]
    query = "仅检索包含“账单收入”的文档片段，保留实际来源引用"
    text = doc.read_text(encoding="utf-8")
    literal = "已付款账单收入按明确的付款状态与账单日期汇总，并核对人民币金额单位。"
    start = text.index(literal)
    info = manifest.sources[0]
    fact = {
        "document_id": info.document_id,
        "version": info.version,
        "source_id": info.source_id,
        "source_sha256": info.version,
        "literal": literal,
        "start": start,
        "end": start + len(literal),
        "chunks": [c.model_dump(mode="json") for c in info.chunks],
    }
    cases = []
    for id_, lane, question in [
        (
            "toy-join",
            "sql_only",
            "复核公开合成账本 2025 年十月已支付收入，保持客户关联后的账单粒度。",
        ),
        ("toy-rag", "rag_only", query),
        ("toy-mixed", "sql_rag", "复核公开合成账本 2025 年十月已支付收入，并附账单口径文档。"),
    ]:
        task = ToyTask.model_validate_json(
            json.dumps(
                {
                    "case_id": id_,
                    "lane": lane,
                    "objective": "公开合成三路径适配验收",
                    "question": question,
                    "owner": rag.owner,
                    "datasets": datasets.model_dump(mode="json"),
                    "metrics": [] if lane == "rag_only" else [request.model_dump(mode="json")],
                    "document_goal": None
                    if lane == "sql_only"
                    else {
                        "goal_id": "documents",
                        "question": query,
                        "metric_goals": [] if lane == "rag_only" else [request.goal_id],
                    },
                    "rag_scope": None if lane == "sql_only" else rag.model_dump(mode="json"),
                }
            )
        )
        gold = ToyGold(
            case_id=id_,
            business_completion="completed",
            host_decision="review_then_run",
            metrics=[]
            if lane == "rag_only"
            else [NumericGold(goal_id="revenue", disposition="verified", value="300", unit="CNY")],
            retrieval=None
            if lane == "sql_only"
            else {
                "disposition": "complete",
                "facts": [fact],
                "relevant_chunk_ids": [c.chunk_id for c in info.chunks],
                "relevant_document_ids": [info.document_id],
                "relevant_source_ids": [info.source_id],
            },
            refusal_conditions=[],
            causal_claim_must_remain_unverified=False,
        )
        assets = {"public-source.xlsx": source}
        if lane != "sql_only":
            assets["billing.md"] = doc
        folder = prepare_launch(
            task,
            phase="toy",
            campaign_id="public-three-lanes",
            pack_hash=digest("public-toy-v2"),
            assets=assets,
        )
        cases.append(
            {
                "task": task.model_dump(mode="json"),
                "gold": gold.model_dump(mode="json"),
                "launch_path": folder.relative_to(ROOT).as_posix(),
                "source_sha256": schema.source_sha256,
            }
        )
    write_new(
        private / "cases.json", {"cases": cases, "fixture": "public_unrelated_toy", "paid_calls": 0}
    )
    print(json.dumps({"public_toy_lanes": 3, "formal_runs": 0}))


def run():
    from p7_business_evaluator import score, summarize, usage_summary

    rows = json.loads((BASE / "private/toy/cases.json").read_bytes())["cases"]
    observations, collections, tasks = {}, [], []
    for row in rows:
        task = ToyTask.model_validate_json(json.dumps(row["task"]))
        gold = ToyGold.model_validate_json(json.dumps(row["gold"]))
        folder = ROOT / row["launch_path"]
        for action in ("probe", "start", "approve", "resume", "collect"):
            run_container(folder, action)
        key = (BASE / "private/collector.key").read_bytes()
        record = json.loads((folder / "collect.json").read_bytes())
        payload = authenticated(record, key)
        result = score(
            task,
            gold,
            record,
            key,
            source_hashes={
                (b.dataset_id, b.version): row["source_sha256"] for b in task.datasets.bindings
            },
            rule={"customer_linkage_and_invoice_grain": task.case_id == "toy-join"},
        )
        if not result["strict_correct"]:
            write_new(folder / "score.json", result)
            raise ValueError("Toy evidence/score failed; preserve all receipts")
        observations[task.case_id] = result
        collections.append(payload)
        tasks.append(task)
    summary = summarize(tasks, observations, mode="toy")
    summary["usage"] = usage_summary(collections)
    summary["scores"] = observations
    write_new(BASE / "toy-three-lanes.json", summary)
    print(
        json.dumps(
            {
                "toy_cases": len(observations),
                "passed": sum(r["strict_correct"] for r in observations.values()),
                "formal_live": "not_run",
            }
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["prepare", "run"])
    {"prepare": prepare, "run": run}[p.parse_args().action]()
