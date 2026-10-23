"""Trusted TEST process driver. Fault controls are deliberately absent from HTTP DTOs."""

import argparse
import os

from datapilot.config import Settings
from datapilot.db.management import management_url
from datapilot.persistence.session import run_async
from datapilot.web.app import create_app
from datapilot.web.config import load_policy
from datapilot.web.store import WebStore
from datapilot.web.worker import execute_one


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("api", "worker"))
    parser.add_argument("policy")
    parser.add_argument("--run-id")
    parser.add_argument("--dispatch", action="store_true")
    parser.add_argument("--cut")
    parser.add_argument("--pause-after")
    args = parser.parse_args()
    os.environ["DATAPILOT_LLM_MODE"] = "fake"
    settings = Settings(llm_mode="fake")
    policy = load_policy(args.policy)
    if args.action == "api":
        import uvicorn

        uvicorn.run(
            create_app(
                policy=policy, settings=settings, dispatch=args.dispatch, policy_file=args.policy
            ),
            host="127.0.0.1",
            port=int(policy.api_host.rsplit(":", 1)[1]),
            access_log=False,
            log_level="critical",
        )
    else:

        def fault(point):
            if point == args.cut:
                os._exit(91)

        store = WebStore(management_url("web"), policy)
        store.settings_provider = lambda: settings
        try:
            run_async(
                execute_one(
                    settings,
                    store,
                    args.run_id,
                    fault=fault,
                    interrupt_after=[args.pause_after] if args.pause_after else None,
                )
            )
        finally:
            store.close()


if __name__ == "__main__":
    main()
