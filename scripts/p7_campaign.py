"""Trusted benchmark host: admission, bounded launch and signed collection, not a Runtime."""

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from p7_business_scoring import sign_collection
from p7_business_v2 import BASE, DEST, load_v2
from p7_gate2b import ROOT, environment, inspect, write_new
from p7_holdout_pack import sha
from sqlalchemy.engine import make_url

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetBinding, DatasetScope
from datapilot.ingestion.common import digest
from datapilot.persistence.session import run_async
from datapilot.rag.mcp import rag_session
from datapilot.reporting.contracts import ReportScope
from datapilot.runtime.mcp_client import dataset_session, metric_session

IMAGE = "datapilot-pro-demo:local"


def settings_for_host():
    env = environment()
    return Settings(
        _env_file=None,
        llm_mode="fake",
        api_key=None,
        max_model_calls=8,
        max_total_tokens=18000,
        max_output_tokens=1200,
        **{
            role + "_database_url": env[f"DATAPILOT_{role.upper()}_DATABASE_URL"]
            for role in ("reader", "upload_reader", "runtime", "rag_reader")
        },
    )


def report_scope(task):
    return ReportScope(
        owner=task.owner,
        question=task.question,
        datasets=task.datasets,
        metrics=task.metrics,
        document_goal=task.document_goal,
        causal_requested=task.causal_requested,
    )


def version_declared(task, pins):
    datasets = {(p["dataset_id"], p["dataset_version"]): p for p in pins["datasets"].values()}
    for request in task.metrics:
        dataset = datasets.get((request.dataset_id, request.dataset_version))
        if not dataset or not any(
            (p["metric_id"], p["metric_version"], p["semantic_version"])
            == (request.metric_id, request.metric_version, request.semantic_version)
            for p in dataset["metric_definitions"]
        ):
            return False
    return True


async def preflight():
    """Only metadata/context; no Holdout search, metric execution, or model call."""
    inspect()
    tasks, pins, anchor = load_v2()
    settings = settings_for_host()
    schemas = {}
    for alias, pin in pins["datasets"].items():
        scope = DatasetScope(
            bindings=[DatasetBinding(dataset_id=pin["dataset_id"], version=pin["dataset_version"])]
        )
        async with dataset_session(settings, scope) as tool:
            schema = await tool.schema(pin["dataset_id"])
        if (schema.source_sha256, schema.version) != (pin["source_sha256"], pin["dataset_version"]):
            raise ValueError("Source snapshot differs from v2")
        schemas[alias] = schema.model_dump(mode="json")
    rag_cache, context_cache, checks = {}, {}, []
    for task in tasks:
        code = None
        try:
            report_scope(task)
            if not version_declared(task, pins):
                code = "VERSION_NOT_AUTHORIZED"
            elif task.rag_scope:
                key = digest(task.rag_scope)
                if key not in rag_cache:
                    try:
                        async with rag_session(settings, task.rag_scope):
                            pass
                        rag_cache[key] = None
                    except AgentFailure as exc:
                        rag_cache[key] = exc.error.code
                code = rag_cache[key]
        except ValueError:
            code = "REPORT_SCOPE_INVALID"
        missing = []
        if code is None:
            for request in task.metrics:
                key = digest(
                    request.model_dump(mode="json", exclude={"goal_id", "window", "as_of"})
                )
                if key not in context_cache:
                    scope = DatasetScope(
                        bindings=[
                            DatasetBinding(
                                dataset_id=request.dataset_id, version=request.dataset_version
                            )
                        ]
                    )
                    try:
                        async with metric_session(settings, scope) as tool:
                            context = await tool.context(request)
                        # Exact reviewed definitions, not merely matching version numbers.
                        pin = next(
                            p
                            for p in pins["datasets"].values()
                            if (p["dataset_id"], p["dataset_version"])
                            == (request.dataset_id, request.dataset_version)
                        )
                        semantic = next(
                            p
                            for p in pin["semantic_definitions"]
                            if p["semantic_version"] == request.semantic_version
                        )
                        metric = next(
                            p
                            for p in pin["metric_definitions"]
                            if (p["metric_id"], p["metric_version"])
                            == (request.metric_id, request.metric_version)
                        )
                        if (context.semantic_sha256, context.metric_sha256) != (
                            semantic["sha256"],
                            metric["sha256"],
                        ):
                            raise ValueError("Registry definitions differ from frozen proposals")
                        context_cache[key] = None
                    except AgentFailure as exc:
                        context_cache[key] = exc.error.code
                if context_cache[key]:
                    missing.append({"goal_id": request.goal_id, "code": context_cache[key]})
        checks.append(
            {
                "case_id": task.case_id,
                "input_error": code,
                "p3_confirmation_missing": missing,
                "executed": False,
                "admission": "preflight_blocked" if code else "pending_p3" if missing else "ready",
            }
        )
    result = {
        "seal_sha256": anchor["seal_sha256"],
        "checked_at": datetime.now(UTC).isoformat(),
        "cases": checks,
        "schemas": schemas,
        "candidate_runs": 0,
        "retrieval_queries": 0,
        "metric_executions": 0,
        "paid_calls": 0,
        "rag_scope_groups_checked": len(rag_cache),
        "context_groups_checked": len(context_cache),
    }
    receipt = BASE / (
        "admission.json"
        if not (BASE / "admission.json").exists()
        else "admission-" + uuid4().hex + ".json"
    )
    write_new(receipt, result)
    pointer = {"path": receipt.relative_to(ROOT).as_posix(), "sha256": sha(receipt.read_bytes())}
    (BASE / "admission-current.json").write_text(
        json.dumps(pointer, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "cases": len(checks),
                "input_rejections": sum(bool(c["input_error"]) for c in checks),
                "pending_p3_cases": sum(bool(c["p3_confirmation_missing"]) for c in checks),
                "candidate_runs": 0,
            }
        )
    )


def read_admission():
    pointer = BASE / "admission-current.json"
    if not pointer.exists():
        return json.loads((BASE / "admission.json").read_bytes())
    ref = json.loads(pointer.read_bytes())
    path = (ROOT / ref["path"]).resolve()
    if not path.is_relative_to(BASE.resolve()) or sha(path.read_bytes()) != ref["sha256"]:
        raise ValueError("Fresh admission pointer changed")
    return json.loads(path.read_bytes())


def permit_valid(permit, *, pack_hash, campaign_id, case_id, config_hash, now=None):
    """Trusted-host file must bind this exact campaign/config and bounded future authority."""
    now = now or datetime.now(UTC)
    if any(
        type(permit.get(k)) is not int
        for k in ("max_runs", "calls_per_run", "tokens_per_run", "concurrency", "automatic_retries")
    ):
        raise ValueError("Strict integer budget fields required")
    if (
        permit.get("kind") != "business-live-authorization"
        or permit.get("approved_by_role") != "project_owner"
        or not permit.get("source_user_authorization_ref")
        or permit.get("pack_sha256") != pack_hash
        or permit.get("campaign_id") != campaign_id
        or permit.get("mode") != "live"
        or permit.get("provider") != "deepseek"
        or permit.get("model") != "deepseek-flash"
        or permit.get("thinking") != "disabled"
        or permit.get("config_hashes", {}).get(case_id) != config_hash
        or permit.get("max_runs") != 60
        or permit.get("calls_per_run") != 8
        or permit.get("tokens_per_run") != 18000
        or permit.get("concurrency") != 1
        or permit.get("automatic_retries") != 0
        or datetime.fromisoformat(permit["expires_at"]) <= now
    ):
        raise ValueError("Fresh exact scoped Live authorization is required")
    if len(permit["config_hashes"]) > 60:
        raise ValueError("Permit cannot enlarge campaign")


def container_settings():
    env = environment()
    values = {
        "llm_mode": "fake",
        "model_provider": "deepseek",
        "model": "deepseek-flash",
        "base_url": "https://api.deepseek.com",
        "max_model_calls": 8,
        "max_total_tokens": 18000,
        "max_output_tokens": 1200,
    }
    for role in ("reader", "upload_reader", "runtime", "rag_reader"):
        values[role + "_database_url"] = (
            make_url(env[f"DATAPILOT_{role.upper()}_DATABASE_URL"])
            .set(host="postgres", port=5432)
            .render_as_string(hide_password=False)
        )
    infrastructure = {
        "DATAPILOT_REGISTRY_DATABASE_URL": make_url(env["DATAPILOT_REGISTRY_DATABASE_URL"])
        .set(host="postgres", port=5432)
        .render_as_string(hide_password=False)
    }
    return values, infrastructure


def prepare_launch(task, *, phase, campaign_id, pack_hash, assets):
    """Call from trusted host only; never accept model-supplied owner/permission fields."""
    if (
        phase not in {"toy", "formal"}
        or (phase == "toy") != task.case_id.startswith("toy-")
        or not re.fullmatch(r"[a-z0-9-]{1,64}", campaign_id)
        or not re.fullmatch(r"bh2-\d{3}|toy-[a-z0-9-]{1,40}", task.case_id)
    ):
        raise ValueError("Formal and public Toy identities cannot be mixed")
    values, infrastructure = container_settings()
    scope = report_scope(task)
    folder = BASE / "private/launch" / campaign_id / task.case_id
    if folder.exists():
        raise ValueError("Preserve launch identity; resume existing frozen launch")
    folder.mkdir(parents=True)
    approved = folder / "assets"
    approved.mkdir()
    closure = {}
    for name, path in assets.items():
        if Path(name).name != name or path.is_symlink():
            raise ValueError("Only exact host-approved regular assets")
        shutil.copyfile(path, approved / name)
        closure[name] = sha(path.read_bytes())
    values["llm_mode"] = "live" if phase == "formal" else "fake"
    config = {
        "schema_version": "business-launch-2",
        "phase": phase,
        "campaign_id": campaign_id,
        "pack_sha256": pack_hash,
        "case_id": task.case_id,
        "owner": task.owner,
        "run_id": str(uuid5(NAMESPACE_URL, campaign_id + pack_hash + task.case_id)),
        "question_sha256": digest(task.question),
        "settings": values,
        "infrastructure_environment": infrastructure,
        "report_scope": scope.model_dump(mode="json"),
        "rag_scope": task.rag_scope.model_dump(mode="json") if task.rag_scope else None,
        "authorized_asset_hashes": closure,
        "lineage_required": task.case_id in {"bh2-001", "toy-join"},
    }
    if phase == "formal":
        _, pins, anchor = load_v2()
        if pack_hash != anchor["seal_sha256"]:
            raise ValueError("Launch must use exact v2 seal")
        config["expected_contexts"] = {}
        for request in task.metrics:
            dataset = next(
                p
                for p in pins["datasets"].values()
                if (p["dataset_id"], p["dataset_version"])
                == (request.dataset_id, request.dataset_version)
            )
            semantic = next(
                p
                for p in dataset["semantic_definitions"]
                if p["semantic_version"] == request.semantic_version
            )
            metric = next(
                p
                for p in dataset["metric_definitions"]
                if (p["metric_id"], p["metric_version"])
                == (request.metric_id, request.metric_version)
            )
            config["expected_contexts"][request.goal_id] = {
                "source_sha256": dataset["source_sha256"],
                "semantic_sha256": semantic["sha256"],
                "metric_sha256": metric["sha256"],
            }
    write_new(folder / "config.json", config)
    write_new(
        folder / "launch-pin.json",
        {
            "config_sha256": sha((folder / "config.json").read_bytes()),
            "run_id": config["run_id"],
            "scope_sha256": digest(scope),
        },
    )
    return folder


def prepare_formal():
    tasks, pins, anchor = load_v2()
    admission = read_admission()
    checks = {c["case_id"]: c for c in admission["cases"]}
    campaign = "business-v2-" + anchor["seal_sha256"][:16]
    launches = []
    for task in tasks:
        if checks[task.case_id]["input_error"]:
            launches.append(
                {
                    "case_id": task.case_id,
                    "stage": "preflight",
                    "reason": checks[task.case_id]["input_error"],
                }
            )
            continue
        assets = {}
        for binding in task.datasets.bindings:
            pin = next(
                p
                for p in pins["datasets"].values()
                if (p["dataset_id"], p["dataset_version"]) == (binding.dataset_id, binding.version)
            )
            path = DEST / "assets" / pin["asset_path"]
            assets[f"{binding.dataset_id}-v{binding.version}{path.suffix}"] = path
        if task.rag_scope:
            for binding in task.rag_scope.corpora:
                item = next(
                    p
                    for p in pins["corpora"].values()
                    if p["index_version"] == binding.index_version
                )
                group = item.get("source_group") or next(
                    alias
                    for alias, p in pins["corpora"].items()
                    if p["index_version"] == binding.index_version
                )
                for source in item["manifest"]["sources"]:
                    if source["document_id"] not in binding.document_ids:
                        raise ValueError("Asset distribution exceeds original grant")
                    assets[source["document_id"] + ".md"] = (
                        DEST / "assets/documents" / group / source["name"]
                    )
        folder = prepare_launch(
            task,
            phase="formal",
            campaign_id=campaign,
            pack_hash=anchor["seal_sha256"],
            assets=assets,
        )
        launches.append(
            {
                "case_id": task.case_id,
                "stage": "runtime",
                "path": folder.relative_to(ROOT).as_posix(),
                "config_sha256": sha((folder / "config.json").read_bytes()),
                "assets": len(assets),
                "p3_pending": bool(checks[task.case_id]["p3_confirmation_missing"]),
            }
        )
    write_new(
        BASE / "launches.json",
        {
            "campaign_id": campaign,
            "cases": launches,
            "pack_sha256": anchor["seal_sha256"],
            "live_authorized": False,
        },
    )
    print(json.dumps({"prepared": len(launches), "executed": 0, "live_authorized": False}))


def run_container(folder, action, *, permit=None):
    from datapilot.persistence.backend import Backend

    # Reuse the original PG lease. No campaign Run, Checkpoint or second budget ledger.
    value = json.loads((folder / "config.json").read_bytes())
    lock = Backend(
        environment()["DATAPILOT_RUNTIME_DATABASE_URL"],
        str(uuid5(NAMESPACE_URL, "p7-campaign-lock:" + value["campaign_id"])),
        value["owner"],
    )
    try:
        with lock.lease():
            return _run_container(folder, action, permit=permit)
    finally:
        lock.close()


def _run_container(folder, action, *, permit=None):
    """One bounded process; no automatic retry or fallback, including on lost response."""
    inspect()
    config_path = folder / "config.json"
    value = json.loads(config_path.read_bytes())
    pin = json.loads((folder / "launch-pin.json").read_bytes())
    if sha(config_path.read_bytes()) != pin["config_sha256"]:
        raise ValueError("Frozen launch changed")
    live = value["phase"] == "formal"
    context_policy = None
    if live:
        policy_ref = json.loads((BASE / "context-policy-index.json").read_bytes())[value["case_id"]]
        context_policy = ROOT / policy_ref["path"]
        if sha(context_policy.read_bytes()) != policy_ref["sha256"]:
            raise ValueError("Prerequisite policy changed")
    if live and action != "probe":
        if permit is None:
            raise ValueError("No business Live authorization in this gate")
        permit_valid(
            permit,
            pack_hash=value["pack_sha256"],
            campaign_id=value["campaign_id"],
            case_id=value["case_id"],
            config_hash=pin["config_sha256"],
        )
        frozen_path = ROOT / "docs/research/p7-business-v2-freeze.json"
        frozen = json.loads(frozen_path.read_bytes())
        if permit.get("implementation_sha256") != sha(frozen_path.read_bytes()):
            raise ValueError("Live permit must bind exact validated implementation")
        for name, expected in frozen["files"].items():
            if sha((ROOT / name).read_bytes()) != expected:
                raise ValueError("Frozen implementation changed")
        # Formal execution also requires a fresh preflight receipt for exactly this seal.
        admission = read_admission()
        row = next(c for c in admission["cases"] if c["case_id"] == value["case_id"])
        negative = json.loads(context_policy.read_bytes())["required_missing"]
        missing = row["p3_confirmation_missing"]
        expected_absence = (
            bool(missing)
            and {m["goal_id"] for m in missing} == set(negative)
            and all(m["code"] == negative[m["goal_id"]]["required_error_code"] for m in missing)
        )
        if admission["seal_sha256"] != value["pack_sha256"] or (
            row["admission"] != "ready" and not expected_absence
        ):
            raise ValueError("Formal execution has unresolved source/P3 admission")
        if action == "approve" and not permit.get("approve_bound_runs"):
            raise ValueError("Original Run review approval is still required")
    elif not live and not value["case_id"].startswith("toy-"):
        raise ValueError("Fake cannot execute formal Holdout")
    output_path = folder / (action + ".json")
    if output_path.exists():
        raise ValueError("Operation receipt exists; do not resend or silently overwrite")
    # Reserve the operation on trusted disk before dispatch. Unknown exits stay blocked;
    # this marker is not a second execution ledger or a retry mechanism.
    with (folder / (action + ".issued")).open("x") as marker:
        marker.write(datetime.now(UTC).isoformat())
    executable = shutil.which("docker") or r"D:\downloads\DockerDesktop\resources\bin\docker.exe"
    name = "p7b-v2-" + value["run_id"][:8] + "-" + action
    args = [
        executable,
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
        "PYTHONPATH=/app/src:/bench",
        "--env",
        "PYTHONUTF8=1",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
    ]
    mounts = [
        (ROOT / "src", "/app/src"),
        (config_path, "/bench/config.json"),
        (folder / "assets", "/bench/assets"),
        (ROOT / "scripts/p7_campaign_worker.py", "/bench/worker.py"),
        (ROOT / "scripts/p7_business_runtime.py", "/bench/p7_business_runtime.py"),
        (ROOT / ".cache/rag-models", "/app/.cache/rag-models"),
        (ROOT / "artifacts/p7/gate2b/empty-fixtures", "/app/tests/fixtures"),
    ]
    if not live:
        mounts.append((ROOT / "scripts/report_recovery_probe.py", "/bench/toy_decisions.py"))
    else:
        mounts.append((context_policy, "/bench/context-policy.json"))
    for source, target in mounts:
        args += ["--mount", f"type=bind,source={source.resolve()},target={target},readonly"]
    process_env = os.environ.copy()
    process_env.pop("DATAPILOT_API_KEY", None)
    if live and action != "probe":
        # Network and Key become available only under a separately supplied future permit.
        if permit.get("egress_network") != "datapilot-p7b_hostaccess":
            raise ValueError("Explicit bounded egress network is required")
        args += ["--network", "datapilot-p7b_hostaccess", "--env", "DATAPILOT_API_KEY"]
        key = Settings().api_key
        if not key:
            raise ValueError("Provider Key not configured")
        process_env["DATAPILOT_API_KEY"] = key.get_secret_value()
    args += [
        "--entrypoint",
        "/app/.venv/bin/python",
        IMAGE,
        "/bench/worker.py",
        action,
        "--config-sha256",
        pin["config_sha256"],
    ]
    if live:
        args += [
            "--policy",
            "/bench/context-policy.json",
            "--policy-sha256",
            sha(context_policy.read_bytes()),
        ]
    result = subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", env=process_env, timeout=240
    )
    # Logs are private. Never propagate raw Docker/SDK errors or credentials into public output.
    (folder / (action + ".stdout")).write_text(result.stdout, encoding="utf-8")
    (folder / (action + ".stderr")).write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(
            "Candidate/Collector exited; preserve issued marker, inspect private logs"
        )
    payload = json.loads(result.stdout)
    key_path = BASE / "private/collector.key"
    if not key_path.exists():
        with key_path.open("xb") as stream:
            stream.write(secrets.token_bytes(32))
    if action == "collect" and value.get("lineage_required"):
        payload["lineage"] = run_async(collect_lineage(payload))
    if action == "collect":
        payload["campaign_pack_sha256"] = value["pack_sha256"]
        payload["live_authorization_ref"] = (
            permit["source_user_authorization_ref"] if live else None
        )
    write_new(output_path, sign_collection(payload, key_path.read_bytes()))
    return payload


async def collect_lineage(payload):
    """Independent post-run scoped MCP JOIN check; never replace original P3 verdict."""
    from sqlglot import exp

    scope = ReportScope.model_validate_json(
        json.dumps(payload["manifest"]["cross_source_report"]["scope"])
    )
    report = payload["snapshot"].get("report") or {}
    bridges = [c["metric"] for c in report.get("claims", []) if c["kind"] == "metric"]
    if len(bridges) != 1 or bridges[0]["request"]["metric_id"] != "paid_invoice_revenue":
        raise ValueError("JOIN proof requires a single original P3 verified revenue")
    bridge = bridges[0]
    request = scope.metrics[0]
    context = bridge["context"]
    field = context["entity"]["fields"]

    def q(name):
        return exp.to_identifier(name, quoted=True).sql(dialect="postgres")

    def lit(value):
        return exp.Literal.string(value).sql(dialect="postgres")

    async with dataset_session(settings_for_host(), scope.datasets) as tools:
        schema = await tools.schema(request.dataset_id)
        if schema.source_sha256 != bridge["source_sha256"]:
            raise ValueError("JOIN proof source changed")
        invoice = next(t for t in schema.tables if t.table_id == context["table"]["table_id"])
        customer = next(t for t in schema.tables if t.source_name == "customers")
        customer_key = "customer_id"
        # P3's minimized amount context intentionally omits unrelated customer keys.
        if any(
            name not in {c.normalized_name for c in table.columns}
            for table, name in ((invoice, customer_key), (customer, customer_key))
        ):
            raise ValueError("Explicit customer relationship columns are missing")
        invoices = "uploads." + q(invoice.physical_name)
        customers = "uploads." + q(customer.physical_name)
        join = f"{invoices} i JOIN {customers} c ON i.{q(customer_key)}=c.{q(customer_key)}"
        filters = (
            f"i.{q(field['invoice_date'])}>={lit(request.window.start.isoformat())}::date "
            f"AND i.{q(field['invoice_date'])}<"
            f"{lit(request.window.end_exclusive.isoformat())}::date "
            f"AND i.{q(field['payment_status'])} IN ("
            + ",".join(lit(s) for s in context["definition"]["paid_values"])
            + ")"
        )
        if "currency" not in field:
            raise ValueError("JOIN proof requires explicit currency column")
        filters += f" AND i.{q(field['currency'])}={lit(context['definition']['currency'])}"
        queries = [
            f"SELECT COUNT(*) AS n,COUNT(DISTINCT {q(field['record_id'])}) AS u FROM {invoices}",
            f"SELECT COUNT(*) AS n,COUNT(DISTINCT {q(customer_key)}) AS u FROM {customers}",
            f"SELECT COUNT(*) AS n,COUNT(DISTINCT i.{q(field['record_id'])}) AS u FROM {join}",
            f"SELECT COALESCE(SUM(i.{q(field['amount'])}),0) AS amount FROM {join} WHERE {filters}",
        ]
        results = []
        for query in queries:
            result = await tools.execute(request.dataset_id, query)
            if result.result.truncated or result.result.row_count != 1:
                raise ValueError("Lineage projection incomplete")
            results.append(result)
    rows = [r.result.rows[0] for r in results]
    grain = rows[0][0] == rows[0][1] == rows[2][0] == rows[2][1] and rows[1][0] == rows[1][1]
    amount = Decimal(str(rows[3][0]))
    if context["entity"]["amount_storage"] == "minor":
        amount /= 100
    verified = grain and amount == Decimal(bridge["value"]["value"])
    return {
        "kind": "trusted_postrun_mcp_join_validation",
        "run_id": payload["run_id"],
        "question_sha256": payload["question_sha256"],
        "verified": verified,
        "source_sha256": schema.source_sha256,
        "dataset_id": schema.dataset_id,
        "dataset_version": schema.version,
        "evidence_ids": [bridge["evidence_id"]],
        "query_refs": [
            {
                "query_sha256": r.query_sha256,
                "result_sha256": r.result_sha256,
                "sql": query,
                "result": r.model_dump(mode="json"),
            }
            for query, r in zip(queries, results, strict=True)
        ],
        "agent_executed_join_claimed": False,
        "p3_verdict_changed": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["preflight", "prepare", "start", "approve", "resume", "collect", "probe"]
    )
    parser.add_argument("--launch", type=Path)
    parser.add_argument("--permit", type=Path)
    options = parser.parse_args()
    if options.action == "preflight":
        run_async(preflight())
    elif options.action == "prepare":
        prepare_formal()
    else:
        if not options.launch:
            parser.error("--launch required")
        permit = json.loads(options.permit.read_bytes()) if options.permit else None
        output = run_container(options.launch, options.action, permit=permit)
        print(
            json.dumps(
                {
                    "action": options.action,
                    "status": output.get("status"),
                    "run_id": output.get("run_id"),
                }
            )
        )
