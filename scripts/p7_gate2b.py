"""Trusted Gate 2B preparation only. No candidate tuning, paid calls, down or delete."""

import argparse
import html
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from p7_holdout_pack import CaseInput, Gold, sha, verify_seal
from p7_isolated_pg import IMAGE, ROLES
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/p7/gate2b"
PRIVATE = BASE / "private"
NAME = "datapilot-p7b-postgres-1"
PROJECT = "datapilot-p7b"
PORT = 55440
DATABASE = "datapilot_p7b"


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def pack():
    public = json.loads((ROOT / "docs/research/p7-independent-business-holdout.json").read_bytes())
    folder = ROOT / public["pack_path"]
    verify_seal(folder, expected_seal_sha256=public["seal_sha256"])
    return folder, public


def docker(*args):
    executable = shutil.which("docker") or r"D:\downloads\DockerDesktop\resources\bin\docker.exe"
    return subprocess.run(
        [executable, *args], check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def inspect():
    info = json.loads(docker("inspect", NAME))[0]
    if (
        info["Name"] != "/" + NAME
        or info["Config"]["Image"] != IMAGE
        or info["Config"]["Labels"].get("datapilot.gate2b.isolated") != "true"
        or info["Config"]["Labels"].get("com.docker.compose.project") != PROJECT
        or not any(m.get("Name") == PROJECT + "_businessdata" for m in info["Mounts"])
    ):
        raise ValueError("Not the explicitly created Gate 2B instance")
    return info


def environment():
    values = json.loads((PRIVATE / "environment.json").read_bytes())
    for key, value in values.items():
        if key.endswith("DATABASE_URL"):
            url = make_url(value)
            if (url.host, url.port, url.database) != ("127.0.0.1", PORT, DATABASE):
                raise ValueError("Gate 2B environment escaped its instance")
    if values.get("DATAPILOT_LLM_MODE") != "fake" or values.get("DATAPILOT_API_KEY"):
        raise ValueError("Gate 2B cannot inherit paid execution authority")
    # Drop inherited model/DB variables; explicit blank key also defeats local .env fallback.
    return {k: v for k, v in os.environ.items() if not k.startswith("DATAPILOT_")} | values


def initialize():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    path = PRIVATE / "environment.json"
    if not path.exists():
        # Never adopt an existing container or volume, including a coincidentally matching name.
        if NAME in docker("ps", "-a", "--format", "{{.Names}}").splitlines():
            raise ValueError("Container already exists without the private creation record")
        if (
            PROJECT + "_businessdata"
            in docker("volume", "ls", "--format", "{{.Name}}").splitlines()
        ):
            raise ValueError("Volume already exists; do not reuse it")
        passwords = {r: secrets.token_urlsafe(28) for r in ("admin", *ROLES)}
        values = {
            "DATAPILOT_LLM_MODE": "fake",
            "DATAPILOT_API_KEY": "",
            "DATAPILOT_RUN_DB_TESTS": "1",
            "DATAPILOT_RUN_LIVE_TESTS": "0",
            "DATAPILOT_MODEL_PROVIDER": "deepseek",
            "DATAPILOT_MODEL": "deepseek-flash",
            "DATAPILOT_BASE_URL": "https://api.deepseek.com",
            "PYTHONUTF8": "1",
        }
        for role, password in passwords.items():
            user = "postgres" if role == "admin" else "datapilot_" + role
            values[f"DATAPILOT_{role.upper()}_DATABASE_URL"] = (
                f"postgresql+psycopg://{user}:{password}@127.0.0.1:{PORT}/{DATABASE}"
            )
            values[f"DATAPILOT_{role.upper()}_PASSWORD"] = password
        write_new(path, values)
        write_new(
            PRIVATE / "compose.json",
            {
                "services": {
                    "postgres": {
                        "image": IMAGE,
                        "container_name": NAME,
                        "labels": {"datapilot.gate2b.isolated": "true"},
                        "environment": {
                            "POSTGRES_DB": DATABASE,
                            "POSTGRES_PASSWORD": passwords["admin"],
                            "POSTGRES_INITDB_ARGS": "--auth-host=scram-sha-256",
                        },
                        "ports": [f"127.0.0.1:{PORT}:5432"],
                        "networks": ["default", "hostaccess"],
                        "volumes": ["businessdata:/var/lib/postgresql/data"],
                        "healthcheck": {
                            "test": ["CMD-SHELL", f"pg_isready -U postgres -d {DATABASE}"],
                            "interval": "2s",
                            "timeout": "2s",
                            "retries": 30,
                        },
                    }
                },
                "volumes": {"businessdata": {}},
                "networks": {"default": {"internal": True}, "hostaccess": {}},
            },
        )
    docker(
        "compose",
        "--project-name",
        PROJECT,
        "--file",
        str(PRIVATE / "compose.json"),
        "up",
        "-d",
        "--pull",
        "never",
    )
    for _ in range(50):
        if inspect()["State"].get("Health", {}).get("Status") == "healthy":
            break
        time.sleep(1)
    else:
        raise RuntimeError("New isolated database is not healthy")
    env = environment()
    log = BASE / "initialization.json"
    records = json.loads(log.read_bytes()) if log.exists() else []
    for command in (["db-init"], ["migrate"], ["runtime-init"], ["seed"], ["health"]):
        if any(r["command"] == command and r["exit_code"] == 0 for r in records):
            continue
        result = subprocess.run(
            [sys.executable, "-m", "datapilot.cli", *command],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
        output = result.stdout + result.stderr
        for value in env.values():
            if len(value) >= 12 and value not in os.environ.values():
                output = output.replace(value, "[REDACTED]")
        records.append({"command": command, "exit_code": result.returncode, "output": output})
        log.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        if result.returncode:
            raise RuntimeError("Isolated initialization failed; inspect redacted receipt")
    engine = sa.create_engine(env["DATAPILOT_READER_DATABASE_URL"], hide_parameters=True)
    try:
        with engine.connect() as conn:
            version = conn.exec_driver_sql("SHOW server_version_num").scalar_one()
            extension = conn.exec_driver_sql(
                "SELECT extversion FROM pg_extension WHERE extname='vector'"
            ).scalar_one()
            customers = conn.exec_driver_sql("SELECT count(*) FROM saas.customers").scalar_one()
        if int(version) // 10000 != 17 or not extension or customers != 240:
            raise ValueError("Fresh isolated PG/extension/seed validation failed")
        receipt = {
            "container": NAME,
            "port": PORT,
            "database": DATABASE,
            "server_version_num": version,
            "pgvector": extension,
            "new_instance_customers": customers,
            "healthy": True,
        }
        record = BASE / "database-verified.json"
        if record.exists():
            if json.loads(record.read_bytes()) != receipt:
                raise ValueError("Isolated database deployment receipt differs")
        else:
            write_new(record, receipt)
    finally:
        engine.dispose()
    print(json.dumps({"container": NAME, "fresh_seed_only": True, "healthy": True}))


def review():
    folder, public = pack()
    inputs = [
        CaseInput.model_validate_json(x)
        for x in (folder / "inputs.jsonl").read_bytes().splitlines()
    ]
    gold = [Gold.model_validate_json(x) for x in (folder / "gold.jsonl").read_bytes().splitlines()]
    pins = json.loads((folder / "pins.json").read_bytes())
    issues, rows = [], []
    manifests = {p["index_version"]: p["manifest"] for p in pins["corpora"].values()}
    for task, expected in zip(inputs, gold, strict=True):
        if task.case_id != expected.case_id:
            raise ValueError("Gold/input identity mismatch")
        if task.rag_scope:
            for pin in task.rag_scope.corpora:
                source = manifests[pin.index_version]
                if set(pin.document_ids) != {s["document_id"] for s in source["sources"]}:
                    issues.append(
                        {"case_id": task.case_id, "code": "PARTIAL_DOCUMENT_PIN_UNSUPPORTED"}
                    )
        if expected.retrieval:
            source_map = {
                s["document_id"]: (group, s)
                for group, p in pins["corpora"].items()
                for s in p["manifest"]["sources"]
            }
            for fact in expected.retrieval["facts"]:
                group, source = source_map[fact["document_id"]]
                raw = (folder / "assets/documents" / group / source["name"]).read_bytes()
                text = raw.decode("utf-8-sig")
                if (
                    sha(raw) != fact["source_sha256"]
                    or text[fact["start"] : fact["end"]] != fact["literal"]
                ):
                    raise ValueError("Gold fact does not locate its immutable source")
                for chunk in fact["chunks"]:
                    part = text[chunk["start"] : chunk["end"]]
                    if sha(part.encode()) != chunk["sha256"]:
                        raise ValueError("Gold chunk hash differs")
                    if chunk["line_start"] != text[: chunk["start"]].count("\n") + 1:
                        raise ValueError("Gold source line differs")
        rows.append(
            {
                "case_id": task.case_id,
                "input": task.model_dump(mode="json"),
                "expected": expected.model_dump(mode="json"),
                "question_sha256": sha(task.question.encode()),
                "review_decision": "pending",
                "reviewer": None,
                "reviewed_at": None,
                "evidence_of_human_confirmation": None,
                "disagreements": [],
                "definition_confirmation": "pending",
                "source_review": "pending",
            }
        )
    audit = {
        "seal_sha256": public["seal_sha256"],
        "cases": rows,
        "human_approved": False,
        "reviewer_independence": "unverified",
        "dataset_definitions": pins["datasets"],
        "corpus_manifests": pins["corpora"],
        "engineering_issues": issues,
    }
    write_new(PRIVATE / "human-review.json", audit)
    content = [
        "<!doctype html><meta charset='utf-8'><title>Private Gold review</title>",
        "<h1>60 条私有 Gold 审核：全部 pending</h1><p>仅供人工审核，不分发给候选。"
        "数值是 Gold 预期，不是已执行 P3 证据。审阅人/时间/确认凭据不可由生成器代填。</p>",
    ]
    for row in rows:
        content.append(
            f"<h2>{row['case_id']}</h2><pre>"
            + html.escape(json.dumps(row, ensure_ascii=False, indent=2))
            + "</pre>"
        )
    with (PRIVATE / "human-review.html").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(content))
    write_new(
        BASE / "review-summary.json",
        {
            "checked_at": datetime.now(UTC).isoformat(),
            "cases": len(rows),
            "pending": len(rows),
            "human_approved": 0,
            "source_fact_integrity": "passed",
            "issues": issues,
            "seal_sha256": public["seal_sha256"],
            "paid_calls": 0,
            "candidate_executions": 0,
        },
    )
    print(json.dumps({"cases": len(rows), "pending": len(rows), "issues": issues}))


def materialize():
    from datapilot.datasets.contracts import ImportRequest
    from datapilot.ingestion.contracts import SchemaConfirmation
    from datapilot.ingestion.service import IngestionService
    from datapilot.rag.contracts import Chunker, IndexManifest, RagScope, Target
    from datapilot.rag.models import LocalEmbedding
    from datapilot.rag.storage import IngestionService as RagIngestion
    from datapilot.rag.storage import make_pin

    inspect()
    env = environment()
    folder, public = pack()
    pins = json.loads((folder / "pins.json").read_bytes())
    receipt_path = BASE / "materialization.json"
    receipt = (
        json.loads(receipt_path.read_bytes())
        if receipt_path.exists()
        else {
            "datasets": {},
            "corpora": {},
            "semantic_metric_confirmation": "blocked_human_review_pending",
            "seal_sha256": public["seal_sha256"],
            "paid_calls": 0,
        }
    )

    def save():
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")

    ingest = IngestionService(env["DATAPILOT_INGEST_DATABASE_URL"], storage_dir=PRIVATE / "sources")
    try:
        for alias, pin in pins["datasets"].items():
            # Already committed imports are retried through the original content-idempotent service.
            result = ingest.import_file(
                folder / "assets" / pin["asset_path"],
                SchemaConfirmation.model_validate_json(json.dumps(pins["confirmations"][alias])),
                ImportRequest(name=pin["import_name"]),
            )
            if (
                result.dataset_id,
                result.version,
                result.source_sha256,
                result.confirmation_sha256,
            ) != (
                pin["dataset_id"],
                pin["dataset_version"],
                pin["source_sha256"],
                pin["confirmation_sha256"],
            ):
                raise ValueError("Materialized Dataset differs from sealed pin")
            receipt["datasets"][alias] = result.model_dump(mode="json")
            save()
    finally:
        ingest.close()
    embedding = LocalEmbedding()  # Original hash checks and CPU inference; no network fallback.
    ingest = RagIngestion(env["DATAPILOT_RAG_INGEST_DATABASE_URL"], embedding)
    try:
        for group, item in pins["corpora"].items():
            expected = IndexManifest.model_validate_json(json.dumps(item["manifest"]))
            target = Target.model_validate_json(expected.target.model_dump_json())
            scope = RagScope.model_validate_json(
                json.dumps(
                    {
                        "owner": target.owner,
                        "corpora": [
                            make_pin(expected, item["index_version"]).model_dump(mode="json")
                        ],
                        "allow_saas": target.dataset_id is None,
                        "datasets": {
                            "bindings": [
                                {"dataset_id": target.dataset_id, "version": target.dataset_version}
                            ]
                            if target.dataset_id
                            else []
                        },
                    }
                )
            )
            paths = [folder / "assets/documents" / group / s.name for s in expected.sources]
            actual, version, reused, usage = ingest.ingest(
                target,
                paths,
                scope=scope,
                reviewed=True,
                chunker=Chunker.model_validate_json(expected.chunker.model_dump_json()),
            )
            if actual != expected or version != item["index_version"]:
                raise ValueError("Materialized index differs from frozen manifest")
            receipt["corpora"][group] = {
                "corpus_id": target.corpus_id,
                "index_version": version,
                "reused": reused,
                "embedding_usage": usage.model_dump(mode="json") if usage else None,
                "sources": len(actual.sources),
                "chunks": sum(len(s.chunks) for s in actual.sources),
            }
            save()
    finally:
        ingest.close()
    print(
        json.dumps(
            {
                "datasets": len(receipt["datasets"]),
                "corpora": len(receipt["corpora"]),
                "semantic_metric_confirmation": receipt["semantic_metric_confirmation"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["review", "initialize", "materialize"])
    args = parser.parse_args()
    {"review": review, "initialize": initialize, "materialize": materialize}[args.action]()
