"""One sequential versioned experiment driver; original PG leases/ledgers/Runtime only."""

import argparse
import json
import os
import secrets
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from p7_business_evaluator import usage_summary
from p7_business_scoring import sign_collection
from p7_smoke_pack import DOCKER
from p7_smoke_run import checked_process
from sqlalchemy.engine import make_url
from v3_common import (
    BASE,
    BUDGET,
    CAMPAIGN,
    OWNER,
    ROOT,
    clean_settings,
    infrastructure,
    load,
    scope,
    verify,
    write_new,
)
from v3_gate import ordinary_failure_may_continue, permit_valid

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import BudgetLimits
from datapilot.persistence.backend import Backend, DurableLedger
from datapilot.persistence.session import run_async
from datapilot.rag.mcp import rag_session
from datapilot.runtime.mcp_client import dataset_session, metric_session


def authority(anchor, launches):
    return {
        "campaign_id": CAMPAIGN,
        "implementation_sha256": anchor["implementation_manifest_sha256"],
        "case_gold_seal_sha256": anchor["case_gold_seal_sha256"],
        "evaluation_seal_sha256": anchor["evaluation_seal_sha256"],
        "budget_policy_sha256": anchor["budget_policy_sha256"],
        "config_hashes": {r["case_id"]: r["config_sha256"] for r in launches},
    }


async def preflight_task(task, pins, settings):
    try:
        scope(task)
    except ValueError:
        return "REPORT_SCOPE_INVALID"
    allowed = {
        (d["schema"]["dataset_id"], d["schema"]["version"]): d for d in pins["datasets"].values()
    }
    for binding in task.datasets.bindings:
        if (binding.dataset_id, binding.version) not in allowed:
            return "VERSION_NOT_AUTHORIZED"
    try:
        if task.rag_scope:
            async with rag_session(settings, task.rag_scope):
                pass
        async with dataset_session(settings, task.datasets) as tools:
            for binding in task.datasets.bindings:
                actual = await tools.schema(binding.dataset_id)
                expected = allowed[(binding.dataset_id, binding.version)]["schema"]
                if actual.source_sha256 != expected["source_sha256"]:
                    raise ValueError("Source hash drift")
                frozen = allowed[(binding.dataset_id, binding.version)].get("table_snapshots", {})
                for table in actual.tables:
                    if table.table_id not in frozen:
                        continue
                    column = table.columns[0].normalized_name
                    query = f'SELECT * FROM "{table.physical_name}" ORDER BY "{column}"'
                    result = await tools.execute(binding.dataset_id, query)
                    if (
                        result.result.truncated
                        or result.result.row_count != table.row_count
                        or result.result_sha256 != frozen[table.table_id]["result_sha256"]
                    ):
                        raise ValueError("Frozen physical table drift")
        if task.metrics:
            async with metric_session(settings, task.datasets) as tools:
                for request in task.metrics:
                    context = await tools.context(request)
                    ds = allowed[(request.dataset_id, request.dataset_version)]
                    metric = next(
                        m
                        for m in ds["metrics"]
                        if (m["metric_id"], m["metric_version"])
                        == (request.metric_id, request.metric_version)
                    )
                    if (context.semantic_sha256, context.metric_sha256) != (
                        ds["semantics"]["definition_sha256"],
                        metric["definition_sha256"],
                    ):
                        raise ValueError("Frozen semantic/metric definition drift")
    except AgentFailure as exc:
        if exc.error.code in {
            "DOCUMENT_NOT_AUTHORIZED",
            "DATASET_NOT_AUTHORIZED",
            "VERSION_NOT_AUTHORIZED",
        }:
            return exc.error.code
        raise
    return None


def container_action(config, folder, mode, action, values, product, deadline, permit_path=None):
    env = {"PYTHONUTF8": "1", "DATAPILOT_LLM_MODE": mode}
    for role in ["reader", "upload_reader", "runtime", "rag_reader", "registry"]:
        env["DATAPILOT_" + role.upper() + "_DATABASE_URL"] = (
            make_url(values["DATAPILOT_" + role.upper() + "_DATABASE_URL"])
            .set(host="postgres", port=5432)
            .render_as_string(hide_password=False)
        )
    if mode == "live":
        from dotenv import dotenv_values

        env["DATAPILOT_API_KEY"] = os.environ.get("DATAPILOT_API_KEY") or dotenv_values(
            ROOT / ".env"
        ).get("DATAPILOT_API_KEY", "")
    path = folder / "private.env"
    path.write_text("\n".join(k + "=" + v for k, v in env.items()) + "\n", encoding="utf-8")
    name = "datapilot-v3-" + config["run_id"][:12]
    command = [
        DOCKER,
        "run",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--network",
        "datapilot-p7-unified_default",
        "--env-file",
        str(path.resolve()),
    ]
    snapshot = ROOT / "artifacts/p7/dev-smoke-v1" / product["source_snapshot"]
    mounts = [
        (snapshot / "src", "/app/src"),
        (folder / "config.json", "/bench/config.json"),
        (ROOT / ".cache/rag-models", "/app/.cache/rag-models"),
        (ROOT / "artifacts/p7/dev-smoke-v1/empty-fixtures", "/app/tests/fixtures"),
        (ROOT / "artifacts/p7/dev-smoke-v1/empty-fixtures", "/app/scripts"),
    ]
    for filename in ["v3_worker.py", "v3_gate.py"]:
        mounts.append((Path(__file__).parent / filename, "/bench/" + filename))
    for filename in ["p7_business_runtime.py", "report_recovery_probe.py"]:
        mounts.append((snapshot / "scripts" / filename, "/bench/" + filename))
    if permit_path:
        mounts.append((permit_path, "/bench/permit.json"))
    for host, target in mounts:
        command += ["-v", str(host.resolve()) + ":" + target + ":ro"]
    command += [
        "--entrypoint",
        "/app/.venv/bin/python",
        product["docker"]["image_id"],
        "/bench/v3_worker.py",
        action,
        "--config",
        "/bench/config.json",
        "--config-sha",
        digest_file(folder / "config.json"),
        "--mode",
        mode,
    ]
    if permit_path:
        command += ["--permit", "/bench/permit.json"]
    output, error, code = checked_process(
        command, env=os.environ.copy(), name=name, deadline=deadline, stop_path=BASE / "STOP"
    )
    for k, value in env.items():
        if len(value) > 8:
            output, error = output.replace(value, "[REDACTED]"), error.replace(value, "[REDACTED]")
        if k.endswith("DATABASE_URL"):
            password = make_url(value).password
            output, error = (
                output.replace(password, "[REDACTED]"),
                error.replace(password, "[REDACTED]"),
            )
    write_new(
        folder / (action + "-process.json"), {"exit_code": code, "stdout": output, "stderr": error}
    )
    if code:
        raise RuntimeError("Candidate process failed; no automatic re-dispatch")
    return json.loads(output)


def digest_file(path):
    from v3_common import sha

    return sha(path.read_bytes())


def settle_known(ledger, ticket, payload):
    usage = payload["snapshot"]["usage"]
    if payload["snapshot"]["unknown"] or not usage["usage_complete"]:
        ledger.settle(ticket, None)
        raise RuntimeError("Uncertain execution/usage; charged reservation, never resend")
    ledger.settle(ticket, usage["total_tokens"])


def execute(permit):
    anchor, manifest, product = verify()
    tasks, pins, _ = load()
    launches = json.loads((BASE / "launches.json").read_bytes())
    permit_valid(permit, authority(anchor, launches))  # Before credentials, SDK or registration.
    values = infrastructure(ROOT / "artifacts/p7/unified-regression/private/environment.json")
    run = str(uuid5(NAMESPACE_URL, CAMPAIGN + anchor["implementation_manifest_sha256"]))
    lock = Backend(values["DATAPILOT_RUNTIME_DATABASE_URL"], run, OWNER)
    destination = BASE / "private/results"
    key = secrets.token_bytes(32)
    states = {t.case_id: "not_run" for t in tasks}
    scores = {}
    partitions = {}
    ticket = None
    ledger = None
    collections = []
    start = time.monotonic()
    try:
        lock.register(
            {
                "campaign": CAMPAIGN,
                "manifest": anchor["implementation_manifest_sha256"],
                "kind": "metadata_lease_not_model_budget",
            },
            BudgetLimits(calls=1, tokens=100),
        )
        with lock.lease():
            destination.mkdir(parents=True, exist_ok=False)
            (destination / "collector.key").write_bytes(key)
            write_new(destination / "permit.json", permit)
            position = 0
            for task in tasks:
                folder = destination / task.case_id
                folder.mkdir(exist_ok=False)
                config = json.loads(
                    (BASE / "private/launches" / (task.case_id + ".json")).read_bytes()
                )
                payload = None
                phase = "preflight"
                try:
                    verify()
                    permit_valid(permit, authority(anchor, launches))
                    if (
                        datetime.fromisoformat(permit["expires_at"]) - datetime.now(UTC)
                    ).total_seconds() < 210:
                        raise TimeoutError("Permit cannot cover the full bounded Run")
                    base = {k: v for k, v in config.items() if k != "authorization_binding"}
                    expected = next(row for row in launches if row["case_id"] == task.case_id)
                    if digest(base) != expected["config_sha256"] or config[
                        "authorization_binding"
                    ] != authority(anchor, launches):
                        raise ValueError("Frozen launch identity drift")
                    if (BASE / "STOP").exists() or time.monotonic() - start >= BUDGET[
                        "campaign_timeout_seconds"
                    ]:
                        raise TimeoutError("Campaign stopped")
                    code = run_async(preflight_task(task, pins, clean_settings(values)))
                    frozen_admission = next(
                        row for row in launches if row["case_id"] == task.case_id
                    )
                    if code != frozen_admission["host_preflight_code"]:
                        raise ValueError("Frozen host authorization outcome drift")
                    if code:
                        payload = {
                            "stage": "preflight",
                            "case_id": task.case_id,
                            "task_sha256": digest(task),
                            "question_sha256": digest(task.question),
                            "preflight_code": code,
                            "model_calls": 0,
                            "business_queries": 0,
                            "retrieval_queries": 0,
                            "report": None,
                            "model_mode": "not_invoked",
                        }
                    else:
                        partition, index = divmod(position, 5)
                        if partition not in partitions:
                            count = BUDGET["partition_runtime_counts"][partition]
                            backend = Backend(
                                values["DATAPILOT_RUNTIME_DATABASE_URL"],
                                str(uuid5(NAMESPACE_URL, run + ":partition:" + str(partition))),
                                OWNER,
                            )
                            limits = BudgetLimits(calls=count, tokens=count * 18000)
                            backend.register(
                                {
                                    "campaign": CAMPAIGN,
                                    "partition": partition,
                                    "freeze": anchor["implementation_manifest_sha256"],
                                },
                                limits,
                            )
                            # The global Campaign PG lease is the unique admission owner.
                            ledger = DurableLedger(backend, limits)
                            if ledger.snapshot().calls or ledger.pending:
                                raise ValueError("Partition already attempted; no reset")
                            partitions[partition] = (backend, ledger)
                        ledger = partitions[partition][1]
                        ticket = ledger.reserve_batch("root", [(0, 18000)])[0]
                        position += 1
                        states[task.case_id] = "dispatched"
                        phase = "dispatch"
                        write_new(folder / "config.json", config)
                        deadline = min(start + 10800, time.monotonic() + 180)
                        for action in ["probe", "start", "approve"]:
                            container_action(
                                config,
                                folder,
                                "live",
                                action,
                                values,
                                product,
                                deadline,
                                destination / "permit.json",
                            )
                        payload = container_action(
                            config,
                            folder,
                            "live",
                            "collect",
                            values,
                            product,
                            deadline,
                            destination / "permit.json",
                        )
                        settle_known(ledger, ticket, payload)
                        ticket = None
                        phase = "collected"
                    collections.append(payload)
                    record = sign_collection(payload, key)
                    write_new(folder / "signed-collection.json", record)
                    phase = "score"
                    scorer = subprocess.run(
                        [
                            os.sys.executable,
                            str(Path(__file__).with_name("v3_score.py")),
                            str(folder / "signed-collection.json"),
                            str(destination / "collector.key"),
                        ],
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                    )
                    if scorer.returncode:
                        raise ValueError("Evaluator failed; stop without changing Gold")
                    result = json.loads(scorer.stdout)
                    write_new(folder / "score.json", result)
                    states[task.case_id] = "observed"
                    scores[task.case_id] = result
                    if not result["strict_correct"] and not ordinary_failure_may_continue(
                        result, payload
                    ):
                        raise ValueError("Hard safety/integrity stop")
                except BaseException as exc:
                    if ticket is not None and ticket in ledger.pending:
                        ledger.settle(ticket, None)
                    ticket = None
                    if states[task.case_id] != "observed":
                        if phase == "dispatch":
                            from p7_run_approved_campaign import unknown_dispatch

                            payload = payload or unknown_dispatch(config, None)
                            payload["unresolved_dispatch"] = True
                            payload["model_mode"] = "live"
                            collections.append(payload)
                            write_new(
                                folder / "unknown-dispatch.json", sign_collection(payload, key)
                            )
                            states[task.case_id] = "unknown"
                        else:
                            states[task.case_id] = (
                                "evaluation_failed"
                                if phase == "score"
                                else "stopped_before_dispatch"
                            )
                    write_new(
                        destination / "stop.json",
                        {
                            "case_id": task.case_id,
                            "error_type": type(exc).__name__,
                            "no_retries": True,
                        },
                    )
                    break
            summary = {
                "planned": 60,
                "states": states,
                "scores": scores,
                "strict_correct": sum(s["strict_correct"] for s in scores.values()),
                "not_run": [k for k, v in states.items() if v == "not_run"],
                "partition_ledgers": {
                    str(k): ledger.snapshot().model_dump() for k, (_, ledger) in partitions.items()
                },
                "call_unit": "whole_Runtime_admissions_not_provider_attempts",
                "usage": usage_summary(collections, product["pricing"]["peak_usd_per_million"]),
            }
            write_new(destination / "summary.json", summary)
            return summary
    finally:
        for backend, _ in partitions.values():
            backend.close()
        lock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--permit", type=Path, required=True)
    args = parser.parse_args()
    execute(json.loads(args.permit.read_bytes()))
