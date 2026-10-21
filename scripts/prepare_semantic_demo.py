"""Prepare only public synthetic data/confirmed demo definitions; no model call or real data."""

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

from datapilot.config import Settings
from datapilot.data.semantic_demo import mapping_draft
from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest
from datapilot.db.management import management_url
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService
from datapilot.runtime.mcp_client import dataset_session
from datapilot.semantics.contracts import MetricDraft, MetricRequest, MetricWindow
from datapilot.semantics.registry import RegistryStore

ROOT = Path(__file__).resolve().parents[1]


async def prepare(output):
    source = ROOT / "tests/fixtures/semantics/saas_metrics.xlsx"
    parsed = parse_file(source, options=ParseOptions(header="present"))
    confirmation = confirm_schema(parsed, propose_schema(parsed), reviewed=True)
    importer = IngestionService(management_url("ingest"), storage_dir=ROOT / "artifacts/p3/sources")
    store = RegistryStore(management_url("registry"))
    try:
        imported = importer.import_file(source, confirmation, ImportRequest(name="p3-saas-demo"))
        scope = DatasetScope(
            bindings=[DatasetBinding(dataset_id=imported.dataset_id, version=imported.version)]
        )
        async with dataset_session(Settings(llm_mode="fake"), scope) as tools:
            schema = await tools.schema(imported.dataset_id)
        draft = mapping_draft(schema)
        semantic = store.confirm_semantics(draft, reviewed=True)
        requests = []
        output.mkdir(parents=True, exist_ok=False)
        (output / "mapping.json").write_text(draft.model_dump_json(indent=2), encoding="utf-8")
        for kind in (
            "paid_invoice_revenue",
            "subscription_churn",
            "customer_churn",
            "active_subscriptions",
            "usage",
            "mrr",
        ):
            definition = MetricDraft(
                dataset_id=schema.dataset_id,
                dataset_version=schema.version,
                semantic_version=semantic.semantic_version,
                metric_id=kind,
            )
            metric = store.confirm_metric(definition, reviewed=True)
            (output / (kind + ".json")).write_text(
                definition.model_dump_json(indent=2), encoding="utf-8"
            )
            requests.append(
                MetricRequest(
                    goal_id=kind,
                    dataset_id=schema.dataset_id,
                    dataset_version=schema.version,
                    semantic_version=semantic.semantic_version,
                    metric_id=kind,
                    metric_version=metric.metric_version,
                    **(
                        {"as_of": date(2025, 10, 31)}
                        if kind == "active_subscriptions"
                        else {
                            "window": MetricWindow(
                                start=date(2025, 10, 1), end_exclusive=date(2025, 11, 1)
                            )
                        }
                    ),
                )
            )
        path = output / "requests.json"
        path.write_text(
            json.dumps([r.model_dump(mode="json") for r in requests], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "status": "prepared_synthetic",
                    "dataset_id": schema.dataset_id,
                    "version": schema.version,
                    "requests": str(path),
                },
                ensure_ascii=False,
            )
        )
    finally:
        importer.close()
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reviewed-synthetic",
        action="store_true",
        required=True,
        help="Confirm only this repository's documented synthetic fixture and SaaS policy",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New directory inside artifacts/"
    )
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "artifacts") or output.exists():
        parser.error("Choose a new directory inside this repository's artifacts/")
    asyncio.run(prepare(output))
