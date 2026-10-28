"""Sequential Dev campaign adapter; reuse original PG lease, DurableLedger and signed Collector."""

import argparse
import json
import os
import secrets
import subprocess
import time
from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from p7_business_evaluator import rag_result, score_preflight, usage_summary
from p7_business_scoring import authenticated, score_case, sign_collection
from p7_holdout_pack import sha
from p7_smoke_pack import (
    BASE,
    DOCKER,
    OWNER,
    PACK,
    POLICY,
    PROFILE,
    ROOT,
    SmokeGold,
    infrastructure,
    load_pack,
    runtime_files,
    settings_for,
    write_new,
)
from p7_smoke_worker import permit_valid
from sqlalchemy.engine import make_url

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import BudgetLimits
from datapilot.persistence.backend import Backend, DurableLedger
from datapilot.persistence.backend import execute as db_execute
from datapilot.persistence.session import run_async
from datapilot.rag.mcp import rag_session
from datapilot.reporting.contracts import ReportScope
from datapilot.runtime.mcp_client import dataset_session, metric_session

ANCHOR = ROOT / "docs/research/p7-new-implementation-freeze-v1.json"


def scope_for(task):
    return ReportScope(
        owner=task.owner,
        question=task.question,
        datasets=task.datasets,
        metrics=task.metrics,
        document_goal=task.document_goal,
        causal_requested=task.causal_requested,
    )


def verify_freeze():
    anchor = json.loads(ANCHOR.read_bytes())
    path = ROOT / anchor["manifest_path"]
    if sha(path.read_bytes()) != anchor["manifest_sha256"]:
        raise ValueError("FREEZE_INVALIDATED: manifest anchor changed")
    manifest = json.loads(path.read_bytes())
    snapshot_root = BASE / manifest["source_snapshot"]
    if snapshot_root.is_symlink() or not snapshot_root.resolve().is_relative_to(BASE.resolve()):
        raise ValueError("FREEZE_INVALIDATED: snapshot escapes the sealed workspace")
    if runtime_files() != manifest["files"]:
        raise ValueError("FREEZE_INVALIDATED: runtime/build closure differs")
    snapshot_files = {
        p.relative_to(snapshot_root).as_posix()
        for p in snapshot_root.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    if snapshot_files != set(manifest["files"]):
        raise ValueError("FREEZE_INVALIDATED: extra/missing executable snapshot file")
    for name, expected in manifest["files"].items():
        target = ROOT / name
        if target.is_symlink() or not target.is_file() or sha(target.read_bytes()) != expected:
            raise ValueError("FREEZE_INVALIDATED: implementation file changed: " + name)
        frozen = snapshot_root / name
        if frozen.is_symlink() or not frozen.is_file() or sha(frozen.read_bytes()) != expected:
            raise ValueError("FREEZE_INVALIDATED: executable snapshot differs")
    _, _, sealed = load_pack()
    if sealed["seal_sha256"] != manifest["case_seal_sha256"]:
        raise ValueError("FREEZE_INVALIDATED: case seal changed")
    if (
        sha((BASE / "evaluation-protocol-v1.json").read_bytes())
        != manifest["evaluation_protocol_sha256"]
        or sha((ROOT / manifest["evaluation_seal_path"]).read_bytes())
        != manifest["evaluation_seal_sha256"]
    ):
        raise ValueError("FREEZE_INVALIDATED: evaluation protocol/scorer seal changed")
    return anchor, manifest


async def table_snapshots(settings, pins):
    """Small synthetic fixtures only: bounded MCP fingerprints, no new snapshot engine."""
    from datapilot.datasets.contracts import DatasetBinding, DatasetScope

    binding = DatasetScope(
        bindings=[DatasetBinding(dataset_id=pins["schema"]["dataset_id"], version=1)]
    )
    snapshots = {}
    async with dataset_session(settings, binding) as tools:
        for table in pins["schema"]["tables"]:
            if table["row_count"] > 100:
                raise ValueError("Smoke fingerprint exceeds the original row limit")
            first = table["columns"][0]["normalized_name"]
            sql = f'SELECT * FROM "{table["physical_name"]}" ORDER BY "{first}"'
            result = await tools.execute(pins["schema"]["dataset_id"], sql)
            if result.result.truncated or result.result.row_count != table["row_count"]:
                raise ValueError("Incomplete synthetic table fingerprint")
            snapshots[table["table_id"]] = {"sql": sql, "result_sha256": result.result_sha256}
    return snapshots


async def preflight(task, pins, values, expected_tables=None):
    settings = settings_for(values)
    if (
        not task.preflight_rejection
        and expected_tables is not None
        and await table_snapshots(settings, pins) != expected_tables
    ):
        raise ValueError("Frozen physical synthetic data changed")
    async with dataset_session(settings, task.datasets) as tools:
        schema = await tools.schema(pins["schema"]["dataset_id"])
        if schema.source_sha256 != pins["schema"]["source_sha256"]:
            raise ValueError("Frozen Dataset/source changed")
    if task.metrics:
        async with metric_session(settings, task.datasets) as tools:
            for request in task.metrics:
                context = await tools.context(request)
                metric = next(m for m in pins["metrics"] if m["metric_id"] == request.metric_id)
                if (context.semantic_sha256, context.metric_sha256) != (
                    pins["semantic"]["definition_sha256"],
                    metric["definition_sha256"],
                ):
                    raise ValueError("Frozen P3 definitions changed")
    code = None
    if task.rag_scope:
        try:
            async with rag_session(settings, task.rag_scope):
                pass
        except AgentFailure as error:
            code = error.error.code
    if code != task.preflight_rejection:
        raise ValueError("Preflight differs from the exact frozen authorization expectation")
    return code


def score(task, gold, record, key, pins):
    payload = authenticated(record, key)
    if task.preflight_rejection:
        result = score_preflight(task, gold, payload)
        result["strict_correct"] &= payload.get("preflight_code") == task.preflight_rejection
        return result
    basic = score_case(
        task,
        gold,
        record,
        key,
        source_hashes={
            (pins["schema"]["dataset_id"], pins["schema"]["version"]): pins["schema"][
                "source_sha256"
            ]
        },
    )
    snapshot = payload["snapshot"]
    report = snapshot.get("report")
    if not report or snapshot["unknown"] or snapshot["next"] or snapshot["review"]:
        return basic | {
            "strict_correct": False,
            "failure_class": failure_class(payload),
        }
    completion = report["business_completion"]
    codes = {c for group in completion["missing_evidence"].values() for c in group}
    missing_correct = all("document_fact_unverified:" + f in codes for f in gold.missing_fact_ids)
    cause_safe = (
        not task.causal_requested
        or "causal_conclusion_not_verified" in completion["unconfirmed_claims"]
    )
    documents = [d for claim in report["claims"] for d in claim["documents"]]
    scope_pins = {p.corpus_id: p for p in task.rag_scope.corpora} if task.rag_scope else {}
    allowed = all(
        d["citation"]["corpus_id"] in scope_pins
        and d["citation"]["index_version"] == scope_pins[d["citation"]["corpus_id"]].index_version
        and d["citation"]["document_id"] in scope_pins[d["citation"]["corpus_id"]].document_ids
        for d in documents
    )
    rag = rag_result(payload, task) if task.document_goal else None
    background = not gold.needs_background or bool(documents)
    receipt_valid = rag is None or bool(rag.get("rag_completion"))
    model_calls = [c for c in payload["calls"] if c["kind"] == "model"]
    accounts = Counter(c["account"] for c in model_calls if c["account"] != "root")
    usage = snapshot["usage"]
    budget = (
        usage["usage_complete"]
        and usage["calls"] <= 8
        and usage["total_tokens"] <= 18000
        and len(model_calls) <= 8
        and all(n <= 4 for n in accounts.values())
    )
    known = all(c["status"] == "complete" for c in payload["calls"])
    correct = basic["strict_correct"] and all(
        [missing_correct, cause_safe, allowed, background, receipt_valid, budget, known]
    )
    failure = (
        None
        if correct
        else "permission_denied"
        if not allowed
        else "retrieval_recall"
        if not background
        else "budget_exceeded"
        if not budget
        else failure_class(payload)
    )
    return basic | {
        "strict_correct": correct,
        "failure_class": failure,
        "missing_facts_correct": missing_correct,
        "causal_safety": cause_safe,
        "citations_authorized": allowed,
        "background_covered": background,
        "rag_worker_complete": bool(rag and rag.get("status") == "succeeded"),
        "rag_receipt_valid": receipt_valid,
        "budget_compliant": budget,
        "durable_known": known,
        "model_calls": len(model_calls),
        "document_fact_coverage": coverage_counts(task.document_goal, report["claims"]),
    }


def coverage_counts(goal, claims):
    # Empty fields are intentionally omitted by the original legacy report serializer.
    coverage = {k: v for c in claims for k, v in c.get("fact_coverage", {}).items()}
    return {
        "required": len(goal.required_facts) if goal else None,
        "verified": sum(v is not None for v in coverage.values()) if goal else None,
        "missing_ids": [k for k, v in coverage.items() if v is None],
    }


def failure_class(payload):
    """Use structured original evidence, never infer an error code from exception text."""
    snapshot = payload.get("snapshot", {})
    if snapshot.get("unknown") or payload.get("unresolved_dispatch"):
        return "unknown_outcome"
    results = snapshot.get("state", {}).get("results", {}).values()
    codes = {r["error"]["code"] for r in results if r.get("error")}
    if codes & {"BUDGET_EXCEEDED", "CONTEXT_LIMIT"}:
        return "budget_exceeded"
    if codes & {"MODEL_ERROR", "MODEL_TIMEOUT"}:
        return "provider_failure"
    if codes & {"MODEL_OUTPUT_INVALID", "PLAN_INVALID"}:
        return "model_reasoning"
    if codes & {"DOCUMENT_NOT_AUTHORIZED", "DATASET_NOT_AUTHORIZED", "TOOL_FORBIDDEN"}:
        return "permission_denied"
    report = snapshot.get("report")
    if report:
        missing = {
            c
            for values in report["business_completion"]["missing_evidence"].values()
            for c in values
        }
        if "snapshot_not_attested" in missing:
            return "snapshot_unsupported"
        if any(
            a["metric"]["verdict"] in {"unavailable", "rejected"}
            for a in payload.get("artifacts", {}).values()
            if a.get("metric")
        ):
            return "P3_rejected"
        if any(
            c.startswith("document_fact_unverified:") or c == "document_conclusion_unverified"
            for c in missing
        ):
            return "insufficient_evidence"
        return "model_reasoning"
    return "infrastructure_failure"


def binding(anchor, tasks):
    return {
        "freeze_sha": anchor["manifest_sha256"],
        "seal_sha": json.loads((BASE / "pack-anchor.json").read_bytes())["seal_sha256"],
        "policy_sha": sha((PACK / "budget.json").read_bytes()),
        "scopes": {t.case_id: digest(scope_for(t)) for t in tasks},
    }


def reserve_case(ledger):
    """One existing-ledger call unit = one whole-Run admission, NOT a provider attempt.

    Seven admissions x at most eight attempts enforces <=56 provider calls. Reserve
    the entire original 18k Run cap before dispatch. Unknown dispatch keeps all 18k.
    """
    return ledger.reserve_batch("root", [(0, POLICY["tokens_per_run"])])[0]


def checked_process(command, *, env, name, deadline, stop_path):
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        while True:
            try:
                output, error = process.communicate(timeout=0.5)
                return output.decode("utf-8"), error.decode("utf-8"), process.returncode
            except subprocess.TimeoutExpired:
                if stop_path.exists() or time.monotonic() >= deadline:
                    subprocess.run([DOCKER, "stop", "--timeout", "2", name], capture_output=True)
                    process.kill()
                    process.communicate()
                    raise TimeoutError(
                        "Stopped/timeout dispatch outcome uncertain; never resend"
                    ) from None
    finally:
        if process.poll() is None:
            subprocess.run([DOCKER, "stop", "--timeout", "2", name], capture_output=True)
            process.kill()
            process.communicate()


def container_action(task, folder, mode, action, values, manifest, deadline):
    config = json.loads((folder / "config.json").read_bytes())
    name = "datapilot-smoke-" + mode + "-" + task.case_id
    environment = {"PYTHONUTF8": "1", "DATAPILOT_LLM_MODE": mode}
    for role in ["reader", "upload_reader", "runtime", "rag_reader", "registry"]:
        u = make_url(values[f"DATAPILOT_{role.upper()}_DATABASE_URL"]).set(
            host="postgres", port=5432
        )
        environment[f"DATAPILOT_{role.upper()}_DATABASE_URL"] = u.render_as_string(
            hide_password=False
        )
    if mode == "live":
        from dotenv import dotenv_values

        environment["DATAPILOT_API_KEY"] = os.environ.get("DATAPILOT_API_KEY") or dotenv_values(
            ROOT / ".env"
        ).get("DATAPILOT_API_KEY", "")
    secret_env = folder / "private.env"
    secret_env.write_text(
        "\n".join(k + "=" + v for k, v in environment.items()) + "\n", encoding="utf-8"
    )
    mounts = [
        (BASE / manifest["source_snapshot"] / "src", "/app/src"),
        (folder / "config.json", "/bench/config.json"),
        (BASE / "empty-fixtures", "/app/tests/fixtures"),
        (ROOT / ".cache/rag-models", "/app/.cache/rag-models"),
    ]
    for name_ in ["p7_smoke_worker.py", "p7_business_runtime.py", "report_recovery_probe.py"]:
        mounts.append((BASE / manifest["source_snapshot"] / "scripts" / name_, "/bench/" + name_))
    if mode == "live":
        mounts.append((folder.parent / "permit.json", "/bench/permit.json"))
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
        str(secret_env.resolve()),
    ]
    for host, target in mounts:
        command += ["-v", str(host.resolve()) + ":" + target + ":ro"]
    command += [
        "--entrypoint",
        "/app/.venv/bin/python",
        manifest["docker"]["image_id"],
        "/bench/p7_smoke_worker.py",
        "collect" if action == "collect-replay" else action,
        "--config",
        "/bench/config.json",
        "--config-sha",
        sha((folder / "config.json").read_bytes()),
        "--mode",
        mode,
    ]
    if mode == "live":
        command += ["--permit", "/bench/permit.json"]
    try:
        output, error, returncode = checked_process(
            command, env=os.environ.copy(), name=name, deadline=deadline, stop_path=BASE / "STOP"
        )
    except BaseException:
        # The original issued/unknown Journal and parent reservation remain authoritative.
        raise
    for value in environment.values():
        if len(value) > 12:
            output, error = output.replace(value, "[REDACTED]"), error.replace(value, "[REDACTED]")
    for k, value in environment.items():
        if k.endswith("DATABASE_URL"):
            password = make_url(value).password
            output, error = (
                output.replace(password, "[REDACTED]"),
                error.replace(password, "[REDACTED]"),
            )
    (folder / (action + ".stderr.log")).write_text(error, encoding="utf-8")
    (folder / (action + ".stdout.log")).write_text(output, encoding="utf-8")
    if returncode:
        raise RuntimeError(
            "Candidate failed; sanitized output retained, never automatically resent"
        )
    data = json.loads(output)
    write_new(folder / (action + ".json"), data)
    if action == "collect":
        data["campaign_pack_sha256"] = config["pack_sha256"]
    return data


def execute(values, mode, permit=None):
    anchor, manifest = verify_freeze()
    tasks, pins, pack = load_pack()
    if mode == "live":
        permit_valid(permit or {}, **binding(anchor, tasks))  # Before credentials/SDK/DB execution.
    if json.loads((PACK / "budget.json").read_bytes()) != POLICY:
        raise ValueError("Budget policy drift")
    campaign_id = "p7-dev-smoke-v1-" + mode
    run_id = str(uuid5(NAMESPACE_URL, campaign_id + anchor["manifest_sha256"]))
    backend = Backend(values["DATAPILOT_RUNTIME_DATABASE_URL"], run_id, OWNER)
    limits = BudgetLimits(calls=7, tokens=90000)
    metadata = {
        "kind": "whole_run_smoke_admission_not_model_ledger",
        "binding": binding(anchor, tasks),
        "mode": mode,
    }
    backend.register(metadata, limits)
    out = BASE / "private/results" / mode
    key = secrets.token_bytes(32)
    results, collections = {}, []
    states = {t.case_id: "not_run" for t in tasks}
    started = time.monotonic()
    try:
        with backend.lease():
            out.mkdir(parents=True, exist_ok=False)  # Duplicate process/campaign cannot rerun.
            (out / "collector.key").write_bytes(key)
            if mode == "live":
                write_new(out / "permit.json", permit)
            ledger = DurableLedger(backend, limits)
            with backend.transaction() as conn:
                count = db_execute(
                    conn, "SELECT count(*) FROM execution.events WHERE run_id=:r", r=run_id
                ).scalar_one()
            if (
                count
                or ledger.pending
                or ledger.snapshot().calls
                or not ledger.snapshot().usage_complete
            ):
                raise ValueError("Campaign already attempted/uncertain; never reset or auto-resume")
            for task in tasks:
                ticket = None
                payload = None
                try:
                    backend.assert_lease()
                    verify_freeze()
                    if (BASE / "STOP").exists() or time.monotonic() - started >= 1800:
                        raise TimeoutError("Campaign stopped before dispatch")
                    code = run_async(
                        preflight(task, pins, values, manifest["database"]["table_snapshots"])
                    )
                    folder = out / task.case_id
                    folder.mkdir(exist_ok=False)
                    if code:
                        payload = {
                            "stage": "preflight",
                            "case_id": task.case_id,
                            "task_sha256": digest(task),
                            "question_sha256": digest(task.question),
                            "preflight_code": code,
                            "model_mode": "not_invoked",
                            "model_calls": 0,
                            "business_queries": 0,
                            "retrieval_queries": 0,
                            "report": None,
                        }
                    else:
                        ticket = reserve_case(ledger)
                        backend.event(
                            {
                                "event": "smoke_run_admitted",
                                "case_id": task.case_id,
                                "max_provider_attempts": 8,
                                "held_token_units": 18000,
                            }
                        )
                        states[task.case_id] = "dispatched"
                        config = {
                            "schema_version": "p7-dev-smoke-launch-1",
                            "case_id": task.case_id,
                            "owner": OWNER,
                            "run_id": str(
                                uuid5(
                                    NAMESPACE_URL,
                                    campaign_id
                                    + anchor["manifest_sha256"]
                                    + pack["seal_sha256"]
                                    + task.case_id,
                                )
                            ),
                            "question_sha256": digest(task.question),
                            "profile": PROFILE,
                            "report_scope": scope_for(task).model_dump(mode="json"),
                            "rag_scope": task.rag_scope.model_dump(mode="json")
                            if task.rag_scope
                            else None,
                            "pack_sha256": pack["seal_sha256"],
                            "authorization_binding": binding(anchor, tasks),
                        }
                        write_new(folder / "config.json", config)
                        deadline = min(started + 1800, time.monotonic() + 180)
                        for action in ["probe", "start", "approve"]:
                            container_action(task, folder, mode, action, values, manifest, deadline)
                        payload = container_action(
                            task, folder, mode, "collect", values, manifest, deadline
                        )
                        if mode == "fake":
                            container_action(
                                task, folder, mode, "replay", values, manifest, deadline
                            )
                            # A second independent process revalidates the same proof closure.
                            after = container_action(
                                task, folder, mode, "collect-replay", values, manifest, deadline
                            )
                            if any(
                                payload[k] != after[k] for k in ["calls", "artifacts", "snapshot"]
                            ):
                                raise ValueError("Completed replay changed durable evidence/usage")
                        usage = payload["snapshot"]["usage"]
                        if payload["snapshot"]["unknown"] or not usage["usage_complete"]:
                            raise RuntimeError("Unknown execution/usage; keep full reservation")
                        ledger.settle(ticket, usage["total_tokens"])
                        ticket = None
                    record = sign_collection(payload, key)
                    write_new(folder / "signed-collection.json", record)
                    gold = next(
                        SmokeGold.model_validate_json(row)
                        for row in (PACK / "gold.jsonl").read_bytes().splitlines()
                        if json.loads(row)["case_id"] == task.case_id
                    )
                    result = score(task, gold, record, key, pins)
                    write_new(folder / "score.json", result)
                    results[task.case_id], states[task.case_id] = result, "observed"
                    collections.append(payload)
                    if not result["strict_correct"]:
                        raise ValueError("Frozen Smoke failed; stop, never adjust Gold or retry")
                except BaseException as error:
                    if ticket is not None:
                        ledger.refresh()
                        if ticket in ledger.pending:
                            ledger.settle(ticket, None)
                    if states[task.case_id] != "observed":
                        if states[task.case_id] == "dispatched":
                            if (
                                payload
                                and payload.get("snapshot")
                                and not payload["snapshot"]["unknown"]
                            ):
                                states[task.case_id] = "failed"
                            else:
                                from p7_run_approved_campaign import unknown_dispatch

                                payload = unknown_dispatch(config, None)
                                payload["model_mode"] = mode
                                states[task.case_id] = "unknown"
                            collections.append(payload)
                            write_new(
                                folder / "failed-collection.json", sign_collection(payload, key)
                            )
                        else:
                            states[task.case_id] = "stopped_before_dispatch"
                    backend.event(
                        {
                            "event": "smoke_campaign_stopped",
                            "case_id": task.case_id,
                            "error_type": type(error).__name__,
                        }
                    )
                    write_new(
                        out / "stop.json",
                        {
                            "case_id": task.case_id,
                            "error_type": type(error).__name__,
                            "automatic_retries": 0,
                        },
                    )
                    break
            summary = {
                "mode": mode,
                "fixture": mode == "fake",
                "planned_cases": 8,
                "states": states,
                "scores": results,
                "passed": sum(r["strict_correct"] for r in results.values()),
                "not_run": [k for k, v in states.items() if v == "not_run"],
                "campaign_admission_ledger": ledger.snapshot().model_dump(),
                "admission_call_unit": "whole_run_slot_not_provider_attempt",
                "usage": usage_summary(collections, manifest["pricing"]["peak_usd_per_million"]),
                "cost_basis": "frozen peak-rate conservative estimate, never an actual bill",
                "real_model_quality": "not_run" if mode == "fake" else "Dev_only",
                "all_cases_observed": all(v == "observed" for v in states.values()),
            }
            write_new(out / "summary.json", summary)
            return summary
    finally:
        backend.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--infrastructure", required=True)
    parser.add_argument("--mode", choices=["fake", "live"], default="fake")
    parser.add_argument("--permit", type=Path)
    args = parser.parse_args()
    summary = execute(
        infrastructure(args.infrastructure),
        args.mode,
        json.loads(args.permit.read_bytes()) if args.permit else None,
    )
    print(
        json.dumps(
            {
                "observed": len(summary["scores"]),
                "passed": summary["passed"],
                "real_model_quality": summary["real_model_quality"],
            }
        )
    )
    raise SystemExit(0 if summary["all_cases_observed"] and summary["passed"] == 8 else 2)
