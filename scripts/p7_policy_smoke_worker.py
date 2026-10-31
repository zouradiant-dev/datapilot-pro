"""Single approved Dev launch. No Gold, scorer, alternate Runtime or model entry point."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from p7_business_runtime import collect

from datapilot.config import Settings
from datapilot.ingestion.common import digest
from datapilot.persistence.session import encode, run_async, run_durable
from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import ReportScope

PROFILE = {
    "model_provider": "deepseek",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "max_model_calls": 8,
    "max_total_tokens": 18000,
    "max_output_tokens": 1200,
    "max_worker_turns": 4,
    "model_timeout_seconds": 30,
}
POLICY = {
    "version": "three-policy-dev-1",
    "cases": 8,
    "runtime_runs": 7,
    "calls_per_run": 8,
    "tokens_per_run": 18000,
    "worker_calls": 4,
    "model_attempts": 56,
    "campaign_tokens": 90000,
    "max_output_tokens": 1200,
    "concurrency": 1,
    "automatic_retries": 0,
    "run_seconds": 180,
    "campaign_seconds": 1800,
    "estimated_usd_cap": "0.108",
    "stop_policy": "ordinary_quality_continue_safety_budget_provider_unknown_stop",
}


def scope_hash(scope, rag):
    return digest(
        {
            "scope": scope.model_dump(mode="json"),
            "rag": rag.model_dump(mode="json") if rag else None,
        }
    )


def permit_valid(permit, binding, *, admission=False, now=None):
    now = now or datetime.now(UTC)
    if (
        permit.get("kind") != "p7-three-policy-live-1"
        or permit.get("authorized") is not True
        or permit.get("approved_by_role") != "project_owner"
        or not permit.get("source_user_authorization_ref")
        or permit.get("approve_bound_runs") is not True
        or permit.get("binding") != binding
        or permit.get("budget") != POLICY
        or (permit.get("provider"), permit.get("model"), permit.get("thinking"))
        != ("deepseek", "deepseek-flash", "disabled")
    ):
        raise ValueError("New exact three-policy Live authority required")
    for key, value in POLICY.items():
        if type(value) is int and type(permit["budget"][key]) is not int:
            raise ValueError("Boolean/float is not budget authority")
    expiry = datetime.fromisoformat(permit["expires_at"])
    required = now + timedelta(seconds=POLICY["campaign_seconds"] + 300) if admission else now
    if expiry.tzinfo is None or expiry <= required:
        raise ValueError("Permit lacks expiry/timezone or full campaign preflight headroom")


async def main(config, mode, action, permit=None):
    if set(config) != {
        "schema_version",
        "case_id",
        "run_id",
        "question_sha256",
        "report_scope",
        "rag_scope",
        "scope_sha256",
        "profile",
        "binding",
    }:
        raise ValueError("Closed launch contract; no Gold or arbitrary launch fields")
    if config["schema_version"] != "three-policy-launch-1" or config["profile"] != PROFILE:
        raise ValueError("Wrong launch schema/profile")
    if mode not in {"fake", "live"}:
        raise ValueError("Explicit fake/live required")
    if mode == "live":
        permit_valid(permit or {}, config["binding"])
        if action == "replay":
            raise ValueError("No Live recovery experiment or blind external resend")
    base = {k: v for k, v in config.items() if k != "binding"}
    if digest(base) != config["binding"]["config_hashes"][mode][config["case_id"]]:
        raise ValueError("Frozen base config changed")
    scope = ReportScope.model_validate_json(json.dumps(config["report_scope"]))
    rag = (
        RagScope.model_validate_json(json.dumps(config["rag_scope"]))
        if config["rag_scope"]
        else None
    )
    if scope_hash(scope, rag) != config["scope_sha256"]:
        raise ValueError("Exact policy/owner/scope hash changed")
    if config["binding"]["scope_hashes"][config["case_id"]] != config["scope_sha256"]:
        raise ValueError("Scope not admitted in this frozen campaign")
    settings = Settings(
        _env_file=None, llm_mode=mode, **PROFILE, **({"api_key": None} if mode == "fake" else {})
    )
    if action == "probe":
        forbidden = [
            "/app/.env",
            "/app/artifacts",
            "/bench/gold.json",
            "/bench/collector.key",
            "/var/run/docker.sock",
        ]
        if any(Path(p).exists() for p in forbidden) or list(Path("/app/tests/fixtures").iterdir()):
            raise ValueError("Candidate mount leaks private evaluation/host files")
        return {"gold_readable": False, "scorer_readable": False, "provider_invoked": False}
    if action == "collect":
        result = await collect(config, settings, scope, rag)
        result["actual_provider_cost_status"] = (
            "not_reconciled" if mode == "live" else "not_applicable_fake"
        )
        return result
    transport = None
    if mode == "fake":
        from original_query_probe import Script
        from partial_evidence_probe import NoModel

        transport = (
            NoModel()
            if action == "replay"
            else Script(scope.document_goal.question if scope.document_goal else "")
        )
    return encode(
        await run_durable(
            settings,
            config["run_id"],
            scope.question,
            owner=scope.owner,
            resume=action in {"approve", "replay"},
            require_review=True,
            approve=True if action == "approve" else None,
            report_scope=scope,
            rag_scope=rag,
            transport=transport,
        )
    )


if __name__ == "__main__":
    import hashlib

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["probe", "start", "approve", "replay", "collect"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha", required=True)
    parser.add_argument("--mode", choices=["fake", "live"], required=True)
    parser.add_argument("--permit", type=Path)
    args = parser.parse_args()
    raw = args.config.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.config_sha:
        raise ValueError("Config bytes changed")
    try:
        result = run_async(
            main(
                json.loads(raw),
                args.mode,
                args.action,
                json.loads(args.permit.read_bytes()) if args.permit else None,
            )
        )
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        from datapilot.contracts import AgentFailure

        if isinstance(exc, AgentFailure):
            print(json.dumps({"error": exc.error.model_dump()}))
            raise SystemExit(2) from None
        raise
