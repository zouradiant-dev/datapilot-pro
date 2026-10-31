"""Sequential, bounded Dev adapter over original DurableLedger/Runtime/Inspector."""

import argparse
import importlib.util
import json
import os
import secrets
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from p7_business_scoring import sign_collection
from p7_holdout_pack import sha
from p7_policy_smoke import Case, Gold, check_freeze, score
from p7_policy_smoke_worker import PROFILE, permit_valid, scope_hash
from p7_smoke_pack import DOCKER, write_new
from p7_smoke_run import checked_process, reserve_case, table_snapshots
from sqlalchemy.engine import make_url

from datapilot.config import Settings
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import BudgetLimits
from datapilot.persistence.backend import Backend, DurableLedger
from datapilot.persistence.backend import execute as db_execute
from datapilot.persistence.session import run_async
from datapilot.rag.mcp import rag_session
from datapilot.runtime.mcp_client import metric_session

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    "p7_policy_smoke_worker.py",
    "p7_business_runtime.py",
    "original_query_probe.py",
    "partial_evidence_probe.py",
    "report_recovery_probe.py",
]


def load(base):
    if base.is_symlink() or not base.resolve().is_relative_to(ROOT / "artifacts/p7"):
        raise ValueError("Use a versioned evaluation pack inside the workspace")
    anchor = json.loads((base / "anchor.json").read_bytes())
    path = base / "implementation.json"
    if sha(path.read_bytes()) != anchor["manifest_sha256"]:
        raise ValueError("Manifest anchor changed")
    manifest = json.loads(path.read_bytes())
    check_freeze(ROOT, manifest)
    for name, expected in manifest["assets"].items():
        path = base / name
        if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
            raise ValueError("Sealed asset escapes the pack")
        if sha((base / name).read_bytes()) != expected:
            raise ValueError("Frozen case/Gold/protocol/evaluator changed")
    cases = [
        Case.model_validate_json(json.dumps(v))
        for v in json.loads((base / "cases.json").read_bytes())
    ]
    if [c.case_id for c in cases] != [f"tps-{i:02}" for i in range(1, 9)]:
        raise ValueError("Eight fixed Dev IDs and order required")
    if sum(c.preflight_denial is None for c in cases) != 7:
        raise ValueError("Seven runtime dispatches and one host denial required")
    binding = {
        "manifest_sha256": anchor["manifest_sha256"],
        "assets": manifest["assets"],
        "scope_hashes": {c.case_id: scope_hash(c.scope, c.rag_scope) for c in cases},
        "config_hashes": manifest["config_hashes"],
    }
    return cases, manifest, binding


def environment(path, manifest):
    # Reuse the already-tested trusted-host guard; never load .env or inherit DSNs.
    spec = importlib.util.spec_from_file_location(
        "portable_guard", ROOT / "tests/reporting_fixtures.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    values = json.loads(path.read_bytes())
    module.validate_environment(values)
    u = make_url(values["DATAPILOT_READER_DATABASE_URL"])
    if [u.host, u.port or 5432, u.database] != manifest["database_identity"]:
        raise ValueError("Frozen isolated database identity changed")
    return values


def settings(values):
    return Settings(
        _env_file=None,
        llm_mode="fake",
        api_key=None,
        **PROFILE,
        **{
            role + "_database_url": values["DATAPILOT_" + role.upper() + "_DATABASE_URL"]
            for role in ["reader", "upload_reader", "runtime", "rag_reader"]
        },
    )


async def preflight(case, cfg, pins):
    if case.preflight_denial:
        from datapilot.contracts import AgentFailure

        try:
            async with rag_session(cfg, case.rag_scope, goal=case.document_goal.question):
                raise ValueError("Host denial unexpectedly authorized")
        except AgentFailure as exc:
            if exc.error.code != case.preflight_denial:
                raise
            return exc.error.code
    if case.scope.metrics:
        if await table_snapshots(cfg, {"schema": pins["_schema"]}) != pins["_table_snapshots"]:
            raise ValueError("Bounded physical source fingerprint changed")
        async with metric_session(cfg, case.scope.datasets) as tools:
            for request in case.scope.metrics:
                context = await tools.context(request)
                expected = pins[case.case_id][request.goal_id]
                if any(getattr(context, k) != v for k, v in expected.items()):
                    raise ValueError("Dataset/Semantic/Metric/source pin changed")
    if case.rag_scope:
        async with rag_session(cfg, case.rag_scope, goal=case.document_goal.question):
            pass
    return None


def base_config(case, mode, source_sha):
    run_id = str(
        uuid5(
            NAMESPACE_URL,
            "three-policy-1:" + mode + ":" + source_sha + ":" + digest(case),
        )
    )
    value = {
        "schema_version": "three-policy-launch-1",
        "case_id": case.case_id,
        "run_id": run_id,
        "question_sha256": digest(case.question),
        "report_scope": case.scope.model_dump(mode="json"),
        "rag_scope": case.rag_scope.model_dump(mode="json") if case.rag_scope else None,
        "scope_sha256": scope_hash(case.scope, case.rag_scope),
        "profile": PROFILE,
    }
    return value


def config_for(case, mode, binding, manifest):
    value = base_config(case, mode, manifest["source_sha256"])
    if digest(value) != binding["config_hashes"][mode][case.case_id]:
        raise ValueError("Base launch differs from frozen config")
    return value | {"binding": binding}


def launch(base, folder, config, manifest, values, mode, action, deadline):
    path = folder / "config.json"
    if not path.exists():
        write_new(path, config)
    env = {"PYTHONUTF8": "1", "DATAPILOT_LLM_MODE": mode}
    for role in ["reader", "upload_reader", "runtime", "rag_reader", "registry"]:
        u = make_url(values["DATAPILOT_" + role.upper() + "_DATABASE_URL"]).set(
            host="postgres", port=5432
        )
        env["DATAPILOT_" + role.upper() + "_DATABASE_URL"] = u.render_as_string(hide_password=False)
    if mode == "live":
        from dotenv import dotenv_values

        env["DATAPILOT_API_KEY"] = os.environ.get("DATAPILOT_API_KEY") or dotenv_values(
            ROOT / ".env"
        ).get("DATAPILOT_API_KEY", "")
    else:
        env["DATAPILOT_API_KEY"] = ""
    secret = folder / "private.env"
    if not secret.exists():
        secret.write_text("\n".join(k + "=" + v for k, v in env.items()) + "\n", encoding="utf-8")
    frozen = ROOT / manifest["snapshot"]
    mounts = [
        (frozen / "src", "/app/src"),
        (path, "/bench/config.json"),
        (base / "empty-fixtures", "/app/tests/fixtures"),
        (ROOT / ".cache/rag-models", "/app/.cache/rag-models"),
    ]
    mounts += [(frozen / "scripts" / s, "/bench/" + s) for s in SCRIPTS]
    if mode == "live":
        mounts.append((folder.parent / "permit.json", "/bench/permit.json"))
    name = "policy-smoke-" + mode + "-" + config["run_id"][:8] + "-" + action
    command = [
        DOCKER,
        "run",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--network",
        manifest["docker_network"],
        "--env-file",
        str(secret),
    ]
    for host, target in mounts:
        command += ["-v", str(host.resolve()) + ":" + target + ":ro"]
    command += [
        "--entrypoint",
        "/app/.venv/bin/python",
        manifest["image_id"],
        "/bench/p7_policy_smoke_worker.py",
        "collect" if action == "collect-replay" else action,
        "--config",
        "/bench/config.json",
        "--config-sha",
        sha(path.read_bytes()),
        "--mode",
        mode,
    ]
    if mode == "live":
        command += ["--permit", "/bench/permit.json"]
    output, error, status = checked_process(
        command, env=os.environ.copy(), name=name, deadline=deadline, stop_path=base / "STOP"
    )
    for key, value in env.items():
        if len(value) >= 8:
            output, error = output.replace(value, "[REDACTED]"), error.replace(value, "[REDACTED]")
        if key.endswith("DATABASE_URL"):
            password = make_url(value).password
            output, error = (
                output.replace(password, "[REDACTED]"),
                error.replace(password, "[REDACTED]"),
            )
    (folder / (action + ".stderr.log")).write_text(error, encoding="utf-8")
    if status:
        (folder / (action + ".stdout.log")).write_text(output, encoding="utf-8")
        raise RuntimeError("Candidate failed; stop and inspect private logs, never resend")
    value = json.loads(output)
    write_new(folder / (action + ".json"), value)
    return value


def execute(base, infrastructure, mode, permit=None):
    cases, manifest, binding = load(base)
    if mode == "live":
        permit_valid(permit or {}, binding, admission=True)  # BEFORE credentials or DB access.
    values = environment(infrastructure, manifest)
    cfg = settings(values)
    pins = json.loads((base / "pins.json").read_bytes())
    owner = "three-policy-admission-1"
    pool_id = str(
        uuid5(NAMESPACE_URL, "three-policy-pool:" + mode + ":" + binding["manifest_sha256"])
    )
    backend = Backend(values["DATAPILOT_RUNTIME_DATABASE_URL"], pool_id, owner)
    out = base / "private/results" / mode
    out.mkdir(parents=True, exist_ok=False)
    key = secrets.token_bytes(32)
    (out / "collector.key").write_bytes(key)
    if mode == "live":
        write_new(out / "permit.json", permit)
    limits = BudgetLimits(calls=7, tokens=90000)
    with backend.engine.connect() as conn:
        if db_execute(conn, "SELECT 1 FROM execution.runs WHERE run_id=:r", r=pool_id).first():
            raise ValueError("Campaign identity already used; no ledger reset/resume")
    backend.register(
        {"kind": "original_whole_run_admission", "binding": binding, "mode": mode}, limits
    )
    observations = []
    states = {c.case_id: "not_run" for c in cases}
    started = time.monotonic()
    stop = None
    try:
        with backend.lease():
            ledger = DurableLedger(backend, limits)
            for case in cases:
                load(base)
                if mode == "live":
                    permit_valid(permit, binding)
                if (base / "STOP").exists() or time.monotonic() - started >= 1800:
                    raise TimeoutError("Campaign STOP/deadline")
                folder = out / case.case_id
                folder.mkdir()
                states[case.case_id] = "preflight"
                code = run_async(preflight(case, cfg, pins))
                if code:
                    payload = {
                        "stage": "preflight",
                        "case_id": case.case_id,
                        "code": code,
                        "question_sha256": digest(case.question),
                        "model_mode": "not_invoked",
                        "case_sha256": digest(case),
                    }
                else:
                    ticket = reserve_case(ledger)
                    states[case.case_id] = "dispatched"
                    config = config_for(case, mode, binding, manifest)
                    deadline = min(started + 1800, time.monotonic() + 180)
                    launch(base, folder, config, manifest, values, mode, "probe", deadline)
                    launch(base, folder, config, manifest, values, mode, "start", deadline)
                    launch(base, folder, config, manifest, values, mode, "approve", deadline)
                    payload = launch(
                        base, folder, config, manifest, values, mode, "collect", deadline
                    )
                    usage = payload["snapshot"]["usage"]
                    if payload["snapshot"]["unknown"] or not usage["usage_complete"]:
                        raise ValueError(
                            "Unknown execution/usage; retain complete parent reservation"
                        )
                    ledger.settle(ticket, usage["total_tokens"])
                    if mode == "fake":
                        launch(base, folder, config, manifest, values, mode, "replay", deadline)
                        replay = launch(
                            base, folder, config, manifest, values, mode, "collect-replay", deadline
                        )
                        for field in ["artifacts", "calls", "manifest_sha256"]:
                            if digest(replay[field]) != digest(payload[field]):
                                raise ValueError(
                                    "Terminal replay changed committed references/calls"
                                )
                        for field in ["report", "usage"]:
                            if digest(replay["snapshot"][field]) != digest(
                                payload["snapshot"][field]
                            ):
                                raise ValueError("Terminal replay changed P3/report or budget")
                signed = sign_collection(payload, key)
                write_new(folder / "signed.json", signed)
                gold = Gold.model_validate_json(
                    json.dumps(json.loads((base / "gold.json").read_bytes())[case.case_id])
                )
                result = score(case, gold, signed, key)
                observations.append(result)
                states[case.case_id] = result["business_completion"]
                write_new(folder / "score.json", result)
                if result["critical"]:
                    raise ValueError("Safety/budget/unknown gate stopped campaign")
            return observations
    except BaseException as exc:
        stop = {"type": type(exc).__name__, "case_id": case.case_id if "case" in locals() else None}
        if "case" in locals() and states[case.case_id] in {"dispatched", "preflight"}:
            states[case.case_id] = (
                "uncertain" if "ledger" in locals() and ledger.pending else "blocked"
            )
        raise
    finally:
        write_new(
            out / "summary.json",
            {
                "states": states,
                "observations": observations,
                "admission": ledger.snapshot().model_dump() if "ledger" in locals() else None,
                "seconds": time.monotonic() - started,
                "mode": mode,
                "stop": stop,
            },
        )
        backend.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--infrastructure", type=Path, required=True)
    parser.add_argument("--mode", choices=["fake", "live"], required=True)
    parser.add_argument("--permit", type=Path)
    a = parser.parse_args()
    result = execute(
        a.pack, a.infrastructure, a.mode, json.loads(a.permit.read_bytes()) if a.permit else None
    )
    print(json.dumps(result, ensure_ascii=False))
