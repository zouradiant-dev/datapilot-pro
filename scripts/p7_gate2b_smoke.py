"""Trusted host Toy container launcher. Never launches any sealed business case."""

import json
import secrets
import shutil
import sys
from uuid import NAMESPACE_URL, uuid4, uuid5

from p7_business_scoring import sign_collection
from p7_gate2b import BASE, ROOT, docker, environment, inspect, write_new
from sqlalchemy.engine import make_url

from datapilot.data.semantic_demo import mapping_draft
from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest
from datapilot.datasets.repository import DatasetRepository
from datapilot.ingestion.common import digest
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService
from datapilot.semantics.contracts import MetricDraft, MetricRequest
from datapilot.semantics.registry import RegistryStore

IMAGE = "datapilot-pro-demo:local"


def prepare():
    inspect()
    env = environment()
    source = ROOT / "tests/fixtures/semantics/saas_metrics.xlsx"
    ingest = IngestionService(
        env["DATAPILOT_INGEST_DATABASE_URL"], storage_dir=BASE / "toy-sources"
    )
    parsed = parse_file(source, options=ParseOptions(header="present"))
    try:
        imported = ingest.import_file(
            source,
            confirm_schema(parsed, propose_schema(parsed), reviewed=True),
            ImportRequest(name="p7b-public-toy"),
        )
    finally:
        ingest.close()
    scope = DatasetScope(
        bindings=[DatasetBinding(dataset_id=imported.dataset_id, version=imported.version)]
    )
    reader = DatasetRepository(env["DATAPILOT_UPLOAD_READER_DATABASE_URL"], scope)
    registry = RegistryStore(env["DATAPILOT_REGISTRY_DATABASE_URL"])
    try:
        schema = reader.schema(imported.dataset_id)
        mapping = registry.confirm_semantics(mapping_draft(schema), reviewed=True)
        metric = registry.confirm_metric(
            MetricDraft(
                dataset_id=imported.dataset_id,
                dataset_version=1,
                semantic_version=mapping.semantic_version,
                metric_id="paid_invoice_revenue",
            ),
            reviewed=True,
        )
    finally:
        registry.close()
        reader.close()
    request = MetricRequest.model_validate_json(
        json.dumps(
            {
                "goal_id": "revenue",
                "dataset_id": imported.dataset_id,
                "dataset_version": 1,
                "semantic_version": mapping.semantic_version,
                "metric_id": "paid_invoice_revenue",
                "metric_version": metric.metric_version,
                "window": {"start": "2025-10-01", "end_exclusive": "2025-11-01"},
            }
        )
    )
    question = "核对 2025 年 10 月已支付账单收入，并给出可复核结果。"
    settings = {
        "llm_mode": "fake",
        "model_provider": "deepseek",
        "model": "deepseek-flash",
        "base_url": "https://api.deepseek.com",
    }
    for role in ("reader", "upload_reader", "runtime", "rag_reader"):
        settings[role + "_database_url"] = (
            make_url(env[f"DATAPILOT_{role.upper()}_DATABASE_URL"])
            .set(host="postgres", port=5432)
            .render_as_string(hide_password=False)
        )
    config = {
        "phase": "gate2b_toy",
        "case_id": "toy-paid-invoice",
        "owner": "p7b-toy-owner",
        "question_sha256": digest(question),
        "run_id": str(uuid5(NAMESPACE_URL, "p7b-public-toy-run-1")),
        "settings": settings,
        "report_scope": {
            "owner": "p7b-toy-owner",
            "question": question,
            "datasets": scope.model_dump(mode="json"),
            "metrics": [request.model_dump(mode="json")],
        },
        "infrastructure_environment": {
            "DATAPILOT_REGISTRY_DATABASE_URL": make_url(env["DATAPILOT_REGISTRY_DATABASE_URL"])
            .set(host="postgres", port=5432)
            .render_as_string(hide_password=False)
        },
    }
    write_new(BASE / "toy-launch/config.json", config)
    (BASE / "empty-fixtures").mkdir(exist_ok=True)
    (BASE / "toy-assets").mkdir(exist_ok=True)
    shutil.copyfile(source, BASE / "toy-assets/snapshot.xlsx")
    print(
        json.dumps(
            {
                "case_id": config["case_id"],
                "run_id": config["run_id"],
                "source": "public_test_fixture",
            }
        )
    )


def command(action, *, probe=False):
    inspect()
    label = action
    if (BASE / ("toy-" + label + ".json")).exists():
        label += "-" + uuid4().hex[:8]
    name = "datapilot-p7b-toy-" + label
    args = [
        "run",
        "--name",
        name,
        "--read-only",
        "--user",
        "10001:10001",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--network",
        "datapilot-p7b_default",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=128m",
        "--env",
        "PYTHONUTF8=1",
        "--env",
        "PYTHONPATH=/app/src",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
    ]
    for source, target in [
        (ROOT / "src", "/app/src"),
        (ROOT / "scripts/p7_business_runtime.py", "/bench/runner.py"),
        (BASE / "toy-launch", "/bench/launch"),
        (BASE / "toy-assets", "/bench/assets"),
        (BASE / "empty-fixtures", "/app/tests/fixtures"),
        (ROOT / ".cache/rag-models", "/app/.cache/rag-models"),
    ]:
        args.extend(["--mount", f"type=bind,source={source.resolve()},target={target},readonly"])
    args.extend(["--entrypoint", "/app/.venv/bin/python", IMAGE])
    if probe:
        args.extend(
            [
                "-c",
                "import json;from pathlib import Path;"
                "assert Path('/bench/launch/config.json').is_file();"
                "assert Path('/app/src/datapilot/__init__.py').is_file();"
                "p=['/app/artifacts/p7/business-holdout/sealed-business-final/gold.jsonl',"
                "'/app/artifacts/p7/gate2b/private/human-review.json','/gold.jsonl',"
                "'/evaluator-only.json','/bench/assets/gold.jsonl'];"
                "assert all(not Path(x).exists() for x in p);"
                "assert not list(Path('/app/tests/fixtures').iterdir());"
                "print(json.dumps({'forbidden_paths':p,'gold_readable':False,'public_fixture_overlay_empty':True}))",
            ]
        )
    else:
        args.extend(["/bench/runner.py", action, "--config", "/bench/launch/config.json"])
    output = docker(*args)
    with (BASE / ("toy-" + label + ".json")).open("x", encoding="utf-8") as stream:
        stream.write(output)
    value = json.loads(output)
    mounts = json.loads(docker("inspect", name))[0]
    write_new(
        BASE / ("mounts-" + label + ".json"),
        {
            "mounts": mounts["Mounts"],
            "network": list(mounts["NetworkSettings"]["Networks"]),
            "user": mounts["Config"]["User"],
            "readonly_rootfs": mounts["HostConfig"]["ReadonlyRootfs"],
        },
    )
    if action == "collect":
        key_path = BASE / "private/collector.key"
        if not key_path.exists():
            with key_path.open("xb") as stream:
                stream.write(secrets.token_bytes(32))
        key = key_path.read_bytes()
        write_new(BASE / ("private/toy-signed-" + label + ".json"), sign_collection(value, key))
        print(
            json.dumps(
                {
                    "case_id": value["case_id"],
                    "run_id": value["run_id"],
                    "business_completion": value["snapshot"]["report"]["business_completion"][
                        "status"
                    ],
                    "collector": "original inspect_run; signed only on trusted host",
                }
            )
        )
    else:
        print(
            json.dumps(
                {
                    "action": action,
                    "status": value.get("status"),
                    "gold_readable": value.get("gold_readable"),
                }
            )
        )


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "prepare":
        prepare()
    else:
        if action not in {"probe", "start", "approve", "resume", "collect"}:
            raise ValueError("Toy operation")
        command(action, probe=action == "probe")
