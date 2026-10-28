"""Read-only-mounted candidate entry; original Durable Runtime and Inspector only."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from p7_business_runtime import collect

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetBinding, DatasetScope
from datapilot.ingestion.common import digest
from datapilot.persistence.session import encode, run_async, run_durable
from datapilot.rag.contracts import RagScope
from datapilot.reporting.contracts import ReportScope
from datapilot.runtime.mcp_client import metric_session


def check_context_observation(expected, actual, error_code, negative):
    if negative:
        if (
            negative["expected_hashes"] != expected
            or error_code != negative["required_error_code"]
            or actual is not None
        ):
            raise ValueError("Intentional missing prerequisite changed")
    elif error_code is not None or actual != expected:
        raise ValueError("Fresh host source/definition policy differs from frozen launch")


async def main(action, config_path, expected_hash, policy_path=None, policy_hash=None):
    raw = config_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("Trusted launch bytes differ")
    value = json.loads(raw)
    if value["schema_version"] != "business-launch-2":
        raise ValueError("Unknown launch contract")
    toy = value["phase"] == "toy"
    if toy != value["case_id"].startswith("toy-"):
        raise ValueError("Toy cannot impersonate formal task")
    probe_key = (
        {"api_key": "probe-only-invalid-no-provider-client"}
        if action == "probe" and not toy
        else {}
    )
    settings = Settings(
        _env_file=None, **value["settings"], **({"api_key": None} if toy else probe_key)
    )
    if (settings.max_model_calls, settings.max_total_tokens, settings.max_output_tokens) != (
        8,
        18000,
        1200,
    ):
        raise ValueError("Campaign cannot enlarge original budget")
    if settings.llm_mode != ("fake" if toy else "live"):
        raise ValueError("No Fake fallback for formal task")
    if set(value["infrastructure_environment"]) != {"DATAPILOT_REGISTRY_DATABASE_URL"}:
        raise ValueError("Only restricted original Registry writer permitted")
    os.environ.update(value["infrastructure_environment"])
    scope = ReportScope.model_validate_json(json.dumps(value["report_scope"]))
    rag = (
        RagScope.model_validate_json(json.dumps(value["rag_scope"])) if value["rag_scope"] else None
    )
    if scope.owner != value["owner"] or digest(scope.question) != value["question_sha256"]:
        raise ValueError("Goal/owner differs from launch")
    if not toy and action != "probe":
        if (
            policy_path is None
            or hashlib.sha256(policy_path.read_bytes()).hexdigest() != policy_hash
        ):
            raise ValueError("Formal prerequisite policy missing or changed")
        policy = json.loads(policy_path.read_bytes())
        if policy["case_id"] != value["case_id"] or policy["config_sha256"] != expected_hash:
            raise ValueError("Prerequisite policy belongs to another launch")
        expected = value["expected_contexts"]
        for request in scope.metrics:
            binding = DatasetScope(
                bindings=[
                    DatasetBinding(dataset_id=request.dataset_id, version=request.dataset_version)
                ]
            )
            async with metric_session(settings, binding) as tool:
                schema = await tool.schema(request.dataset_id)
                if schema.source_sha256 != expected[request.goal_id]["source_sha256"]:
                    raise ValueError("Missing-context negative cannot change source authorization")
                code, context = None, None
                try:
                    context = await tool.context(request)
                except AgentFailure as exc:
                    code = exc.error.code
            actual = (
                {
                    k: getattr(context, k)
                    for k in ("source_sha256", "semantic_sha256", "metric_sha256")
                }
                if context is not None
                else None
            )
            check_context_observation(
                expected[request.goal_id],
                actual,
                code,
                policy["required_missing"].get(request.goal_id),
            )
    for name, expected in value["authorized_asset_hashes"].items():
        if (
            Path(name).name != name
            or hashlib.sha256((config_path.parent / "assets" / name).read_bytes()).hexdigest()
            != expected
        ):
            raise ValueError("Authorized snapshot changed")
    if action == "probe":
        forbidden = [
            "/app/.git",
            "/app/.env",
            "/app/artifacts",
            "/bench/gold.jsonl",
            "/gold.jsonl",
            "/bench/collector.key",
            "/var/run/docker.sock",
        ]
        if any(Path(p).exists() for p in forbidden) or list(Path("/app/tests/fixtures").iterdir()):
            raise ValueError("Candidate mount closure exposes forbidden data")
        return {
            "gold_readable": False,
            "private_key_readable": False,
            "approved_assets": len(value["authorized_asset_hashes"]),
            "run_id": value["run_id"],
            "model_invoked": False,
        }
    if action == "collect":
        return await collect(value, settings, scope, rag)
    transport = None
    if toy and rag:
        from toy_decisions import ReportDecisions

        transport = ReportDecisions(scope.document_goal.question)
    result = await run_durable(
        settings,
        value["run_id"],
        scope.question,
        owner=scope.owner,
        resume=action != "start",
        require_review=True,
        approve=True if action == "approve" else None,
        report_scope=scope,
        rag_scope=rag,
        transport=transport,
    )
    return encode(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["probe", "start", "approve", "resume", "collect"])
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--config", type=Path, default=Path("/bench/config.json"))
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--policy-sha256")
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                run_async(
                    main(
                        args.action,
                        args.config,
                        args.config_sha256,
                        args.policy,
                        args.policy_sha256,
                    )
                ),
                ensure_ascii=False,
            )
        )
    except AgentFailure as exc:
        print(json.dumps({"error": exc.error.model_dump()}))
        raise SystemExit(2) from None
