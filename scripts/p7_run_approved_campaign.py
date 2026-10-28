"""Sequential future experiment driver. Requires new explicit signed-off host permit."""

import argparse
import json
import secrets
import shutil
from uuid import NAMESPACE_URL, uuid5

from p7_business_scoring import sign_collection
from p7_business_v2 import BASE, load_v2
from p7_campaign import (
    _run_container,
    permit_valid,
    report_scope,
    settings_for_host,
    version_declared,
)
from p7_gate2b import ROOT, environment, write_new
from p7_holdout_pack import sha

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.persistence.backend import Backend
from datapilot.persistence.session import run_async
from datapilot.rag.mcp import rag_session


async def rejection_observation(task, pins):
    code = None
    try:
        report_scope(task)
        if not version_declared(task, pins):
            code = "VERSION_NOT_AUTHORIZED"
        elif task.rag_scope:
            async with rag_session(settings_for_host(), task.rag_scope):
                pass
    except ValueError:
        code = "REPORT_SCOPE_INVALID"
    except AgentFailure as exc:
        code = exc.error.code
    return {
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
        "metadata_preflight_only": True,
    }


def execute(permit):
    tasks, pins, anchor = load_v2()
    launches = json.loads((BASE / "launches.json").read_bytes())
    rows = {r["case_id"]: r for r in launches["cases"]}
    if set(permit.get("config_hashes", {})) != {t.case_id for t in tasks}:
        raise ValueError("Exact future 60-case authorization required")
    for task in tasks:
        permit_valid(
            permit,
            pack_hash=anchor["seal_sha256"],
            campaign_id=launches["campaign_id"],
            case_id=task.case_id,
            config_hash=rows[task.case_id].get("config_sha256") or digest(task),
        )
    if not permit.get("approve_bound_runs"):
        raise ValueError("Original bound Run scopes require explicit host approval")
    freeze_path = ROOT / "docs/research/p7-business-v2-freeze.json"
    if permit.get("implementation_sha256") != sha(freeze_path.read_bytes()):
        raise ValueError("Implementation differs from future approval")
    for name, expected in json.loads(freeze_path.read_bytes())["files"].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError("Frozen implementation changed")
    backend = Backend(
        environment()["DATAPILOT_RUNTIME_DATABASE_URL"],
        str(uuid5(NAMESPACE_URL, "p7-campaign-lock:" + launches["campaign_id"])),
        tasks[0].owner,
    )
    destination = BASE / "private/campaign-results" / launches["campaign_id"]
    try:
        with backend.lease():
            destination.mkdir(parents=True, exist_ok=False)
            key_path = BASE / "private/collector.key"
            if not key_path.exists():
                with key_path.open("xb") as stream:
                    stream.write(secrets.token_bytes(32))
            shutil.copyfile(key_path, destination / "collector.key")
            for task in tasks:
                backend.assert_lease()
                row = rows[task.case_id]
                if row["stage"] == "preflight":
                    payload = run_async(rejection_observation(task, pins))
                    if payload["preflight_code"] != row["reason"]:
                        raise ValueError("Preflight changed; no business task executed")
                    payload.update(
                        campaign_pack_sha256=anchor["seal_sha256"],
                        live_authorization_ref=permit["source_user_authorization_ref"],
                    )
                    record = sign_collection(payload, key_path.read_bytes())
                else:
                    folder = ROOT / row["path"]
                    try:
                        for action in ("start", "approve", "collect"):
                            _run_container(folder, action, permit=permit)
                    except Exception:
                        config = json.loads((folder / "config.json").read_bytes())
                        payload = unknown_dispatch(config, permit["source_user_authorization_ref"])
                        write_new(
                            destination / (task.case_id + ".json"),
                            sign_collection(payload, key_path.read_bytes()),
                        )
                        raise RuntimeError(
                            "Dispatch outcome retained as unknown; no retry or budget reset"
                        ) from None
                    record = json.loads((folder / "collect.json").read_bytes())
                    payload = record["payload"]
                write_new(destination / (task.case_id + ".json"), record)
                if row["stage"] == "runtime" and (
                    payload["snapshot"]["unknown"]
                    or payload["snapshot"]["next"]
                    or payload["snapshot"]["review"]
                    or payload["snapshot"]["state"].get("status") in {"failed", "cancelled"}
                ):
                    raise ValueError(
                        "Failed/uncertain result retained; stop without automatic retry"
                    )
    finally:
        backend.close()


def unknown_dispatch(config, authorization_ref):
    """Host observed failure, not an invented provider call/usage receipt."""
    return {
        "case_id": config["case_id"],
        "run_id": config["run_id"],
        "question_sha256": config["question_sha256"],
        "campaign_pack_sha256": config["pack_sha256"],
        "live_authorization_ref": authorization_ref,
        "model_mode": "live",
        "unresolved_dispatch": True,
        "manifest": {
            "cross_source_report": {"scope": config["report_scope"]},
            "rag_scope": config["rag_scope"],
        },
        "manifest_sha256": None,
        "calls": [],
        "artifacts": {},
        "actual_provider_cost": None,
        "snapshot": {
            "unknown": True,
            "next": True,
            "review": False,
            "report": None,
            "state": {"status": "failed"},
        },
        "failure_class": "dispatch_failed_execution_and_usage_unconfirmed",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--permit", required=True)
    options = parser.parse_args()
    from pathlib import Path

    execute(json.loads(Path(options.permit).read_bytes()))
