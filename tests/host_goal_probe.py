"""Trusted test-only process entry; original Durable, no paid transport or model tools."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def legacy_goal(question, retrieval=None, report_scope=None):
    """Fixed public synthetic identity, never executable private code or a fallback."""
    from datapilot.ingestion.common import digest

    frozen = json.loads((ROOT / "tests/fixtures/rag/host-goal-legacy-identity.json").read_bytes())
    policy = getattr(retrieval, "relevance_policy", "bge-host-goal-cosine-v1")
    goal = frozen["goals"].get(policy)
    if (
        question != frozen["query"]
        or goal is None
        or getattr(retrieval, "goal_threshold", 0.55) != goal["minimum_goal_score"]
        or digest(goal) != frozen["goal_sha256"][policy]
    ):
        raise ValueError("Legacy test fixture requires its exact public query and policy")
    return goal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "resume"])
    parser.add_argument("run_id")
    parser.add_argument("config")
    parser.add_argument("--pause", action="store_true")
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--v2", action="store_true")
    parser.add_argument("--v3", action="store_true")
    parser.add_argument("--cut")
    args = parser.parse_args()
    if args.legacy:
        import datapilot.orchestration.rag_completion as control

        control.retrieval_goal = legacy_goal
    if args.v2:
        import datapilot.orchestration.rag_completion as control

        frozen = json.loads((ROOT / "tests/fixtures/rag/host-goal-v2-identity.json").read_bytes())

        def v2_goal(question, retrieval=None, report_scope=None):
            assert question == frozen["query"]
            return frozen["goals"][retrieval.relevance_policy].copy()

        control.retrieval_goal = v2_goal
    if args.v3:
        import datapilot.orchestration.rag_completion as control

        frozen = json.loads((ROOT / "tests/fixtures/rag/host-goal-v3-identity.json").read_bytes())

        def v3_goal(question, retrieval=None, report_scope=None):
            assert question == frozen["query"]
            return frozen["goals"][retrieval.relevance_policy].copy()

        control.retrieval_goal = v3_goal

    from datapilot.cli import json_default
    from datapilot.config import Settings
    from datapilot.contracts import AgentFailure
    from datapilot.persistence.session import run_async, run_durable
    from datapilot.rag.contracts import RagScope
    from datapilot.reporting.contracts import ReportScope

    sys.path.insert(0, str(ROOT / "scripts"))
    from report_recovery_probe import ReportDecisions

    raw = json.loads(Path(args.config).read_bytes())
    rag = RagScope.model_validate_json(json.dumps(raw["rag_scope"]))
    report = ReportScope.model_validate_json(json.dumps(raw["report_scope"]))

    def fault(point):
        if point == args.cut:
            os._exit(91)

    try:
        result = run_async(
            run_durable(
                Settings(llm_mode="fake", api_key=None),
                args.run_id,
                report.question if args.action == "start" else None,
                owner=report.owner,
                resume=args.action == "resume",
                rag_scope=rag,
                report_scope=report,
                transport=ReportDecisions(report.document_goal.question),
                interrupt_after=["worker"] if args.pause else None,
                fault=fault,
            )
        )
    except AgentFailure as exc:
        print(json.dumps({"error": exc.error.model_dump()}))
        raise SystemExit(2) from None
    print(json.dumps(result, default=json_default, ensure_ascii=False))


if __name__ == "__main__":
    main()
