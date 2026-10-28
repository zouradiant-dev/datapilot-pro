"""New Dev launch adapter over original Durable/Collector, without Gold or authoring code."""

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from p7_business_runtime import collect

from datapilot.config import Settings
from datapilot.ingestion.common import digest
from datapilot.persistence.session import encode, run_async, run_durable
from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import ReportScope


def permit_valid(permit, *, freeze_sha, seal_sha, policy_sha, scopes, now=None):
    """Preparation never creates approval. A later trusted host must bind exact new authority."""
    now = now or datetime.now(UTC)
    if (
        permit.get("kind") != "p7-dev-smoke-live-authorization-1"
        or permit.get("authorized") is not True
        or permit.get("approved_by_role") != "project_owner"
        or not permit.get("source_user_authorization_ref")
        or permit.get("freeze_sha256") != freeze_sha
        or permit.get("case_seal_sha256") != seal_sha
        or permit.get("budget_policy_sha256") != policy_sha
        or permit.get("scope_hashes") != scopes
        or permit.get("approve_bound_runs") is not True
        or (permit.get("provider"), permit.get("model"), permit.get("thinking"))
        != ("deepseek", "deepseek-flash", "disabled")
        or permit.get("estimated_usd_cap") != "0.108"
    ):
        raise ValueError("New exact explicit Smoke authorization required; old permits never apply")
    expected = {
        "max_cases": 8,
        "runtime_runs": 7,
        "calls_per_run": 8,
        "tokens_per_run": 18000,
        "campaign_model_calls": 56,
        "campaign_token_units": 90000,
        "concurrency": 1,
        "automatic_retries": 0,
        "max_output_tokens": 1200,
        "task_timeout_seconds": 180,
        "campaign_timeout_seconds": 1800,
    }
    if any(type(permit.get(k)) is not int or permit[k] != v for k, v in expected.items()):
        raise ValueError("Authorization budget must match the sealed proposal exactly")
    expiry = datetime.fromisoformat(permit["expires_at"])
    if expiry.tzinfo is None or expiry <= now:
        raise ValueError("Smoke authorization expired or lacks timezone")


async def main(config, mode, action, permit=None):
    if (
        config["schema_version"] != "p7-dev-smoke-launch-1"
        or not re.fullmatch(r"smoke-0[1-8]", config["case_id"])
        or mode not in {"fake", "live"}
    ):
        raise ValueError("Only new Dev identities, never an old Holdout launch")
    if mode == "live":
        permit_valid(permit or {}, **config["authorization_binding"])
        if action == "replay":
            raise ValueError("Automatic Live recovery experiments are outside this Smoke")
    profile = config["profile"]
    if tuple(
        profile[k]
        for k in ["max_model_calls", "max_total_tokens", "max_output_tokens", "max_worker_turns"]
    ) != (8, 18000, 1200, 4) or (
        profile["model_provider"],
        profile["model"],
        profile["base_url"],
    ) != ("deepseek", "deepseek-flash", "https://api.deepseek.com"):
        raise ValueError("Frozen provider/resource configuration changed")
    settings = Settings(
        _env_file=None, llm_mode=mode, **profile, **({"api_key": None} if mode == "fake" else {})
    )
    scope = ReportScope.model_validate_json(json.dumps(config["report_scope"]))
    rag = (
        RagScope.model_validate_json(json.dumps(config["rag_scope"]))
        if config["rag_scope"]
        else None
    )
    if scope.owner != config["owner"] or digest(scope.question) != config["question_sha256"]:
        raise ValueError("Task identity changed")
    if action == "probe":
        forbidden = [
            "/app/.git",
            "/app/.env",
            "/bench/gold.jsonl",
            "/bench/collector.key",
            "/var/run/docker.sock",
        ]
        if any(Path(p).exists() for p in forbidden):
            raise ValueError("Candidate closure exposes host/Gold/credentials")
        return {"provider_called": False, "gold_readable": False, "collector_key_readable": False}
    if action == "collect":
        payload = await collect(config, settings, scope, rag)
        payload["actual_provider_cost_status"] = (
            "not_provided_by_provider" if mode == "live" else "not_applicable_fake"
        )
        return payload
    transport = None
    if mode == "fake":
        from report_recovery_probe import ReportDecisions

        transport = ReportDecisions(scope.document_goal.question if scope.document_goal else "")
    if action == "replay":

        class NoModel:
            async def respond(self, *_):
                raise AssertionError("Completed replay must reuse committed model responses")

        transport = NoModel()
    return encode(
        await run_durable(
            settings,
            config["run_id"],
            scope.question,
            owner=scope.owner,
            resume=action != "start",
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
    parser.add_argument("action", choices=["probe", "start", "approve", "collect", "replay"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--config-sha", required=True)
    parser.add_argument("--mode", choices=["fake", "live"], required=True)
    parser.add_argument("--permit", type=Path)
    args = parser.parse_args()
    if hashlib.sha256(args.config.read_bytes()).hexdigest() != args.config_sha:
        raise ValueError("Trusted launch bytes changed")
    value = json.loads(args.config.read_bytes())
    print(
        json.dumps(
            run_async(
                main(
                    value,
                    args.mode,
                    args.action,
                    json.loads(args.permit.read_bytes()) if args.permit else None,
                )
            ),
            ensure_ascii=False,
        )
    )
