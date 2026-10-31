"""Only the minimal versioned candidate launch/Collector adapter, never authoring/Gold."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from p7_business_runtime import collect
from v3_gate import permit_valid

from datapilot.config import Settings
from datapilot.ingestion.common import digest
from datapilot.persistence.session import encode, run_async, run_durable
from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import ReportScope


async def execute(config, mode, action, permit):
    probe = config.get("synthetic_probe") is True
    if mode == "live":
        permit_valid(permit, config["authorization_binding"])
        if probe or not re.fullmatch(r"p7-holdout-v3-\d{3}", config["case_id"]):
            raise ValueError("Wrong live namespace")
        expected = config["authorization_binding"]["config_hashes"][config["case_id"]]
        if digest({k: v for k, v in config.items() if k != "authorization_binding"}) != expected:
            raise ValueError("Permit does not bind the exact host launch")
    elif not probe or not re.fullmatch(r"probe-v3-[a-z0-9-]+", config["case_id"]):
        raise ValueError("Fake cannot execute a formal Holdout case")
    profile = config["profile"]
    if (
        profile["max_model_calls"],
        profile["max_total_tokens"],
        profile["max_output_tokens"],
        profile["max_worker_turns"],
    ) != (8, 18000, 1200, 4):
        raise ValueError("Original Root/Child limits unchanged")
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
        raise ValueError("Host identity mismatch")
    if action == "probe":
        forbidden = [
            "/app/.git",
            "/app/.env",
            "/bench/gold.jsonl",
            "/bench/collector.key",
            "/var/run/docker.sock",
            "/bench/v3_sources.py",
            "/app/evaluation/p7_v3/v3_sources.py",
        ]
        if any(Path(p).exists() for p in forbidden):
            raise ValueError("Candidate exposes evaluation secrets")
        return {"gold_readable": False, "collector_key_readable": False, "provider_called": False}
    if action == "collect":
        result = await collect(config, settings, scope, rag)
        result["actual_provider_cost_status"] = (
            "not_provided_by_provider" if mode == "live" else "not_applicable_fake"
        )
        return result
    transport = None
    if mode == "fake":
        from report_recovery_probe import ReportDecisions

        transport = ReportDecisions(scope.document_goal.question if scope.document_goal else "")
    if action == "replay":
        if mode != "fake":
            raise ValueError("No automatic Live replay")

        class NoModel:
            async def respond(self, *_):
                raise AssertionError("Completed replay must not call a model")

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
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["probe", "start", "approve", "collect", "replay"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha", required=True)
    parser.add_argument("--mode", choices=["fake", "live"], required=True)
    parser.add_argument("--permit")
    args = parser.parse_args()
    raw = Path(args.config).read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.config_sha:
        raise ValueError("Launch hash mismatch")
    print(
        json.dumps(
            run_async(
                execute(
                    json.loads(raw),
                    args.mode,
                    args.action,
                    json.loads(Path(args.permit).read_bytes()) if args.permit else None,
                )
            ),
            ensure_ascii=False,
        )
    )
