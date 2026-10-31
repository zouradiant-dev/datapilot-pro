"""Isolated test process driver: reuse the Web outbox worker, no new runtime."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from datapilot.config import Settings
from datapilot.db.management import management_url
from datapilot.persistence.session import run_async
from datapilot.web.config import load_policy
from datapilot.web.service import ProductService
from datapilot.web.store import WebStore
from datapilot.web.worker import execute_one
from scripts.report_recovery_probe import ReportDecisions


def main():
    p = argparse.ArgumentParser()
    p.add_argument("policy")
    p.add_argument("run_id")
    p.add_argument("--settings", required=True)
    p.add_argument("--pause-after")
    args = p.parse_args()
    assert os.environ.get("DATAPILOT_TEST_ISOLATED") == "1"
    settings = Settings(
        _env_file=None,
        llm_mode="fake",
        api_key=None,
        **json.loads(Path(args.settings).read_bytes()),
        **{
            role + "_database_url": os.environ["DATAPILOT_" + role.upper() + "_DATABASE_URL"]
            for role in ("reader", "upload_reader", "runtime", "rag_reader")
        },
    )
    policy = load_policy(args.policy)
    store = WebStore(management_url("web"), policy)
    store.settings_provider = lambda: settings
    try:
        row = run_async(ProductService(settings, store).authorize_run(args.run_id))
        scope = row["payload"]["report_scope"]
        goal = scope.get("document_goal")
        result = run_async(
            execute_one(
                settings,
                store,
                args.run_id,
                transport=ReportDecisions(goal["question"] if goal else ""),
                interrupt_after=[args.pause_after] if args.pause_after else None,
            )
        )
        print({"executed": result}, flush=True)
    finally:
        store.close()


if __name__ == "__main__":
    main()
