"""Thin HTTP study driver. Never reads Gold or approves a contract during collection."""

import argparse
import json
import os
import secrets
import sys
import time

from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest
from datapilot.ingestion.common import digest
from datapilot.persistence.backend import execute
from datapilot.persistence.session import run_async
from datapilot.rag.contracts import CorpusPin, RagScope
from datapilot.rag.mcp import rag_session
from datapilot.runtime.mcp_client import dataset_session
from datapilot.web.client import APIClient
from datapilot.web.config import load_policy
from datapilot.web.store import WebStore

from .common import HERE, OUT, ROOT, cases, verify, write_new

sys.path.insert(0, str(ROOT / "tests"))
from reporting_fixtures import validate_environment  # noqa:E402

sys.path.insert(0, str(ROOT / "scripts"))
from p7_business_scoring import sign_collection  # noqa:E402
from report_recovery_probe import ReportDecisions  # noqa:E402


def configured():
    values = json.loads((OUT / "environment-private.json").read_bytes())
    settings = validate_environment(values)
    os.environ.update(values)
    os.environ.update(DATAPILOT_API_KEY="", DATAPILOT_LLM_MODE="fake", DATAPILOT_RUN_LIVE_TESTS="0")
    return values, settings


def serve():
    import uvicorn

    from datapilot.web.app import create_app

    values, settings = configured()
    policy = load_policy(OUT / "private/host.json")
    public = settings.model_dump(
        mode="json",
        exclude={
            "api_key",
            "llm_mode",
            "reader_database_url",
            "upload_reader_database_url",
            "runtime_database_url",
            "rag_reader_database_url",
        },
    )
    p = OUT / "private/captured-settings.json"
    if not p.exists():
        write_new(p, public)
    else:
        assert json.loads(p.read_bytes()) == public
    uvicorn.run(
        create_app(policy=policy, settings=settings, dispatch=False),
        host="127.0.0.1",
        port=8027,
        access_log=False,
        log_level="warning",
    )


def prepare():
    verify()
    values, settings = configured()
    policy = load_policy(OUT / "private/host.json")
    client = APIClient(OUT / "private/host.json")
    try:
        preview = client.post(
            "/uploads", files={"file": ("invoices.csv", (HERE / "invoices.csv").read_bytes())}
        )
        id_ = preview["upload_id"]
        confirmed = client.post(
            f"/uploads/{id_}/confirm",
            {"proposal_sha256": preview["proposal_sha256"], "reviewed": True},
        )
        ds = client.post(
            f"/uploads/{id_}/import",
            {
                "confirmation_sha256": confirmed["confirmation"]["confirmation_sha256"],
                "name": "gc7-public-snapshot",
            },
        )
        schema = client.get(f"/datasets/{ds['dataset_id']}/versions/{ds['version']}")["schema"]
        semantic = client.post(
            "/semantics/confirm",
            {
                "reviewed": True,
                "draft": {
                    "dataset_id": ds["dataset_id"],
                    "dataset_version": ds["version"],
                    "entities": [
                        {
                            "entity": "invoices",
                            "table_id": schema["tables"][0]["table_id"],
                            "fields": {
                                "record_id": "invoice_id",
                                "amount": "amount_cents",
                                "invoice_date": "invoice_date",
                                "payment_status": "payment_status",
                                "currency": "currency",
                            },
                            "grain": ["invoice_id"],
                            "amount_storage": "minor",
                            "coverage_start": "2026-03-01",
                            "coverage_end_exclusive": "2026-05-01",
                        }
                    ],
                },
            },
        )
        metric = client.post(
            "/metrics/confirm",
            {
                "reviewed": True,
                "draft": {
                    "dataset_id": ds["dataset_id"],
                    "dataset_version": ds["version"],
                    "semantic_version": semantic["semantic_version"],
                    "metric_id": "paid_invoice_revenue",
                },
            },
        )
        texts = json.loads((HERE / "sources.json").read_bytes())
        texts["release-batch.md"] = (
            "公开合成发布提醒规则：每批最多64条提醒，超出项目保留到下一批；聚合收件人前先排除退订租户。本文不包含实际客户投递结果。"
        )
        pins = []
        for name, text in texts.items():
            doc = client.post(
                f"/datasets/{ds['dataset_id']}/versions/{ds['version']}/documents",
                files={"file": (name, text.encode())},
                data={"reviewed": "true"},
            )
            assert doc["embedding_fixture"] is False
            pins.append(doc)
        scope = DatasetScope(
            bindings=[DatasetBinding(dataset_id=ds["dataset_id"], version=ds["version"])]
        )
        store = WebStore(values["DATAPILOT_WEB_DATABASE_URL"], policy)
        try:
            raw = [CorpusPin.model_validate(x["payload"]) for x in store.corpora()]
        finally:
            store.close()

        # Manifest's version is carried by the authorized pin, not text returned by a model.
        async def manifest_sources():
            async with rag_session(
                settings, RagScope(owner=policy.owner, datasets=scope, corpora=raw)
            ) as tools:
                return {
                    s.name: {
                        **s.model_dump(mode="json"),
                        "corpus_id": cid,
                        "index_version": next(p.index_version for p in raw if p.corpus_id == cid),
                    }
                    for cid, m in tools.manifests.items()
                    for s in m.sources
                }

        sources = run_async(manifest_sources())
        # A real other-owner Dataset, not merely a nonexistent UUID.
        from datapilot.ingestion.confirmation import confirm_schema
        from datapilot.ingestion.parser import parse_file
        from datapilot.ingestion.profiling import propose_schema
        from datapilot.ingestion.service import IngestionService

        parsed = parse_file(HERE / "invoices.csv")
        confirmation = confirm_schema(parsed, propose_schema(parsed), reviewed=True)
        ingestor = IngestionService(
            values["DATAPILOT_INGEST_DATABASE_URL"], storage_dir=OUT / "private/foreign-uploads"
        )
        try:
            foreign = ingestor.import_file(
                HERE / "invoices.csv", confirmation, ImportRequest(name="gc7-foreign-owner")
            )
        finally:
            ingestor.close()

        async def foreign_schema():
            async with dataset_session(
                settings,
                DatasetScope(
                    bindings=[
                        DatasetBinding(dataset_id=foreign.dataset_id, version=foreign.version)
                    ]
                ),
            ) as tools:
                return await tools.schema(foreign.dataset_id)

        fs = run_async(foreign_schema())
        other = WebStore(
            values["DATAPILOT_WEB_DATABASE_URL"],
            policy.model_copy(update={"owner": "gc7-foreign-owner"}),
        )
        try:
            other.grant(fs)
        finally:
            other.close()
        binding = {
            "dataset": ds,
            "schema": schema,
            "semantic": semantic,
            "metric": metric,
            "sources": sources,
            "foreign": {"dataset_id": foreign.dataset_id, "version": foreign.version},
            "model_profile": "bge-default-512",
            "definition_approval": "synthetic engineering host only; not human semantic review",
        }
        write_new(OUT / "bindings.json", binding)
        if not (OUT / "private/collector-key.bin").exists():
            (OUT / "private/collector-key.bin").write_bytes(secrets.token_bytes(32))
        print(
            json.dumps(
                {
                    "ready": True,
                    "sources": len(sources),
                    "dataset_version": ds["version"],
                    "paid_calls": 0,
                }
            )
        )
    finally:
        client.close()


def selection(case, binding):
    ds = binding["foreign"] if case.foreign_dataset else binding["dataset"]
    result = {"dataset_id": ds["dataset_id"], "dataset_version": ds.get("version", 1)}
    if case.metric:
        result.update(
            metric_id=case.metric,
            metric_version=binding["metric"]["metric_version"],
            window=case.window,
        )
    if case.source_names:
        result.update(
            corpus_ids=[binding["sources"][name]["corpus_id"] for name in case.source_names],
            document_purpose=case.purpose,
        )
        result["required_source_ids"] = [
            binding["sources"][name]["source_id"] for name in case.source_names
        ]
        if case.facts:
            result["required_facts"] = case.facts
    return result


def collect():
    verify()
    values, _ = configured()
    binding = json.loads((OUT / "bindings.json").read_bytes())
    key = (OUT / "private/collector-key.bin").read_bytes()
    policy = load_policy(OUT / "private/host.json")
    client = APIClient(OUT / "private/host.json")
    store = WebStore(values["DATAPILOT_WEB_DATABASE_URL"], policy)
    try:
        for case in cases():
            verify()
            path = OUT / "collections" / f"{case.id}.json"
            if path.exists():
                raise ValueError("No replay or overwrite of an observed contract")
            with store.transaction() as c:
                before = set(
                    execute(
                        c, "SELECT run_id FROM execution.web_runs WHERE owner=:o", o=policy.owner
                    ).scalars()
                )
            started = time.perf_counter()
            cid = client.post("/conversations", {})["conversation_id"]
            message = None
            error = None
            status = 200
            from uuid import uuid4

            response = client.http.post(
                f"/api/v1/conversations/{cid}/messages",
                json={"text": case.query, "selection": selection(case, binding)},
                headers={"Idempotency-Key": uuid4().hex},
            )
            status = response.status_code
            if response.is_error:
                error = response.json().get("error")
            else:
                message = response.json()
            with store.transaction() as c:
                after = set(
                    execute(
                        c, "SELECT run_id FROM execution.web_runs WHERE owner=:o", o=policy.owner
                    ).scalars()
                )
                payload = None
                if message:
                    row = (
                        execute(
                            c,
                            "SELECT payload,payload_hash FROM execution.web_messages "
                            "WHERE message_id=:m",
                            m=message["message_id"],
                        )
                        .mappings()
                        .one()
                    )
                    assert digest(row["payload"]) == row["payload_hash"]
                    payload = row["payload"]
            attestation = bool(
                payload
                and (payload.get("goal_contract") or {})
                .get("payload", {})
                .get("report_scope", {})
                .get("goal_scope_attestation")
            )
            data = {
                "case_id": case.id,
                "input_sha256": digest(case.model_dump()),
                "conversation_id": cid,
                "message": message,
                "http_status": status,
                "error": error,
                "server_snapshot": payload,
                "new_run_ids": sorted(after - before),
                "attestation_present": attestation,
                "seconds": time.perf_counter() - started,
                "confirmation_attempts": 0,
                "semantic_review": "NOT_VERIFIED",
            }
            write_new(path, sign_collection(data, key))
            print(case.id, status, bool((message or {}).get("goal_contract")), flush=True)
            if after - before or attestation:
                write_new(
                    OUT / "STOP", {"case": case.id, "reason": "unreviewed_execution_or_attestation"}
                )
                break
    finally:
        client.close()
        store.close()


def worker(run_id):
    from datapilot.config import Settings
    from datapilot.web.service import ProductService
    from datapilot.web.worker import execute_one

    values, _ = configured()
    public = json.loads((OUT / "private/captured-settings.json").read_bytes())
    settings = Settings(
        _env_file=None,
        llm_mode="fake",
        api_key=None,
        **public,
        **{
            r + "_database_url": values["DATAPILOT_" + r.upper() + "_DATABASE_URL"]
            for r in ["reader", "upload_reader", "runtime", "rag_reader"]
        },
    )
    store = WebStore(values["DATAPILOT_WEB_DATABASE_URL"], load_policy(OUT / "private/host.json"))
    store.settings_provider = lambda: settings
    try:
        row = run_async(ProductService(settings, store).authorize_run(run_id))
        goal = row["payload"]["report_scope"].get("document_goal")
        run_async(
            execute_one(
                settings, store, run_id, transport=ReportDecisions(goal["question"] if goal else "")
            )
        )
        print(json.dumps({"run_id": run_id, "worked": True}))
    finally:
        store.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["serve", "prepare", "collect", "worker"])
    p.add_argument("--run-id")
    args = p.parse_args()
    if args.action == "worker":
        worker(args.run_id)
    else:
        globals()[args.action]()


if __name__ == "__main__":
    main()
