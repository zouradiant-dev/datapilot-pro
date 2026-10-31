"""Pre-seal schema confirmation repair; append v2, never alter the v1 failure evidence."""

import json

from v3_common import BASE, ROOT, infrastructure, write_new

from datapilot.datasets.contracts import DatasetScope, ImportRequest
from datapilot.datasets.repository import DatasetRepository
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ConfirmationOverrides, ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService
from datapilot.semantics.contracts import MetricDraft, SemanticDraft
from datapilot.semantics.registry import RegistryStore


def repair(values):
    original = json.loads((BASE / "bindings.json").read_bytes())
    old = original["datasets"]["future"]
    table = next(t for t in old["schema"]["tables"] if t["source_name"] == "subscriptions")
    source = BASE / "sources/future.xlsx"
    parsed = parse_file(source, options=ParseOptions(header="present"))
    overrides = ConfirmationOverrides.model_validate_json(
        json.dumps(
            {
                "columns": [
                    {"table_id": table["table_id"], "column": "end_date", "logical_type": "DATE"}
                ]
            }
        )
    )
    confirmation = confirm_schema(
        parsed, propose_schema(parsed), reviewed=True, overrides=overrides
    )
    ingest = IngestionService(
        values["DATAPILOT_INGEST_DATABASE_URL"], storage_dir=BASE / "private/snapshots"
    )
    try:
        imported = ingest.import_file(
            source, confirmation, ImportRequest(name="p7-chengyue-v3-future")
        )
    finally:
        ingest.close()
    assert imported.dataset_id == old["schema"]["dataset_id"] and imported.version == 2
    scope = DatasetScope.model_validate_json(
        json.dumps({"bindings": [{"dataset_id": imported.dataset_id, "version": 2}]})
    )
    repo = DatasetRepository(values["DATAPILOT_UPLOAD_READER_DATABASE_URL"], scope)
    try:
        schema = repo.schema(imported.dataset_id)
    finally:
        repo.close()
    registry = RegistryStore(values["DATAPILOT_REGISTRY_DATABASE_URL"])
    try:
        draft = old["semantics"]["definition"]
        draft["dataset_version"] = 2
        semantic = registry.confirm_semantics(
            SemanticDraft.model_validate_json(json.dumps(draft)), reviewed=True
        )
        metrics = []
        for prior in old["metrics"]:
            definition = prior["definition"]
            definition["dataset_version"] = 2
            metrics.append(
                registry.confirm_metric(
                    MetricDraft.model_validate_json(json.dumps(definition)), reviewed=True
                ).model_dump(mode="json")
            )
    finally:
        registry.close()
    original["datasets"]["future"] = {
        "schema": schema.model_dump(mode="json"),
        "scope": scope.model_dump(mode="json"),
        "semantics": semantic.model_dump(mode="json"),
        "metrics": metrics,
    }
    write_new(BASE / "bindings-v2.json", original)
    write_new(
        BASE / "source-confirmation-revision.json",
        {
            "dataset_id": imported.dataset_id,
            "old_version": 1,
            "new_version": 2,
            "source_sha256_unchanged": schema.source_sha256 == old["schema"]["source_sha256"],
            "column": "subscriptions.end_date",
            "old_type": "TEXT",
            "new_type": "DATE",
            "reason": (
                "All-null end dates require explicit host Schema Co"
                "nfirmation; no product/Gold business-rule change"
            ),
            "preserve_old_version_and_rejected_preparation_record": True,
            "paid_requests": 0,
        },
    )


if __name__ == "__main__":
    repair(infrastructure(ROOT / "artifacts/p7/unified-regression/private/environment.json"))
