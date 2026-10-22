"""Explicit host deployment and maintenance; no HTTP administrative shortcuts."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from datapilot.web.config import ROOT, bootstrap, load_policy


def container_connections():
    from dotenv import load_dotenv
    from sqlalchemy.engine import make_url

    load_dotenv()
    for name, value in list(os.environ.items()):
        if name.startswith("DATAPILOT_") and name.endswith("_DATABASE_URL"):
            os.environ[name] = (
                make_url(value)
                .set(host="postgres", port=5432)
                .render_as_string(hide_password=False)
            )


def main():
    parser = argparse.ArgumentParser(description="DataPilot trusted local product host")
    parser.add_argument(
        "--host-file",
        type=Path,
        default=Path(os.environ.get("DATAPILOT_WEB_HOST_FILE", ROOT / "artifacts/web/host.json")),
    )
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser(
        "bootstrap", help="Explicitly create private host policy; never migrate/seed"
    )
    for name in ("serve", "launch"):
        command = commands.add_parser(name)
        command.add_argument("--mode", choices=("fake", "live"), default="fake")
        if name == "serve":
            command.add_argument(
                "--container",
                action="store_true",
                help="Internal container listener; publish loopback ports only",
            )
    grant = commands.add_parser("grant", help="Host explicitly grants an existing Dataset snapshot")
    grant.add_argument("dataset_id")
    grant.add_argument("version", type=int)
    grant.add_argument("--reviewed", action="store_true")
    retention = commands.add_parser("retention", help="Maintenance only, defaults to dry-run")
    retention.add_argument("run_id")
    retention.add_argument("--execute", action="store_true")
    retention.add_argument("--reviewed", action="store_true")
    retention.add_argument("--confirm-hash")
    retention.add_argument("--hold", choices=("on", "off"))
    retention.add_argument("--reason", default="host review")
    args = parser.parse_args()
    try:
        if args.action == "bootstrap":
            bootstrap(args.host_file)
            result = {"status": "host_configured", "path": str(args.host_file), "secret": "private"}
        elif args.action == "retention":
            from datapilot.db.management import management_url
            from datapilot.persistence.retention import Retainer

            retainer = Retainer(management_url("maintenance"))
            try:
                if args.hold:
                    if not args.reviewed:
                        raise ValueError("Host review required")
                    retainer.hold(args.run_id, active=args.hold == "on", reason=args.reason)
                    result = {"status": "hold_updated"}
                elif args.execute:
                    result = retainer.purge(
                        args.run_id, reviewed=args.reviewed, confirm_hash=args.confirm_hash
                    )
                else:
                    result = retainer.plan(args.run_id)
            finally:
                retainer.close()
        elif args.action == "grant":
            if not args.reviewed:
                raise ValueError("Host review required")
            from datapilot.config import Settings
            from datapilot.datasets.contracts import DatasetBinding, DatasetScope
            from datapilot.db.management import management_url
            from datapilot.persistence.session import run_async
            from datapilot.runtime.mcp_client import dataset_session
            from datapilot.web.store import WebStore

            store = WebStore(management_url("web"), load_policy(args.host_file))

            async def grant_source():
                scope = DatasetScope(
                    bindings=[DatasetBinding(dataset_id=args.dataset_id, version=args.version)]
                )
                async with dataset_session(Settings(llm_mode="fake"), scope) as tools:
                    store.grant(await tools.schema(args.dataset_id))

            try:
                run_async(grant_source())
            finally:
                store.close()
            result = {"status": "dataset_granted"}
        elif args.action == "serve":
            import uvicorn

            if args.container:
                container_connections()
            policy = load_policy(args.host_file)
            if policy.api_host != "127.0.0.1:8000":
                raise ValueError("Default host requires loopback port 8000")
            os.environ["DATAPILOT_WEB_HOST_FILE"] = str(args.host_file.resolve())
            os.environ["DATAPILOT_LLM_MODE"] = args.mode
            uvicorn.run(
                "datapilot.web.app:factory",
                factory=True,
                host="0.0.0.0" if args.container else "127.0.0.1",
                port=8000,
                access_log=False,
                log_level="critical",
            )
            return 0
        else:
            bootstrap(args.host_file)
            common = {
                **os.environ,
                "DATAPILOT_WEB_HOST_FILE": str(args.host_file.resolve()),
                "PYTHONUTF8": "1",
            }
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            api = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "datapilot.web.cli",
                    "--host-file",
                    str(args.host_file),
                    "serve",
                    "--mode",
                    args.mode,
                ],
                env=common,
                creationflags=flags,
            )
            ui_env = {
                k: v
                for k, v in common.items()
                if not k.endswith(("DATABASE_URL", "PASSWORD", "API_KEY"))
                and not k.startswith("POSTGRES_")
            }
            ui = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "streamlit",
                    "run",
                    str(ROOT / "src/datapilot/web/ui.py"),
                    "--server.address",
                    "127.0.0.1",
                    "--server.port",
                    "8501",
                    "--server.headless",
                    "true",
                    "--browser.gatherUsageStats",
                    "false",
                ],
                env=ui_env,
                creationflags=flags,
            )
            print("UI: http://127.0.0.1:8501; API: http://127.0.0.1:8000/api/v1; Ctrl+C stops host")
            try:
                ui.wait()
            except KeyboardInterrupt:
                pass
            finally:
                for child in (ui, api):
                    if child.poll() is None:
                        child.terminate()
                        child.wait(timeout=15)
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        from datapilot.contracts import AgentFailure

        print(
            json.dumps(
                {
                    "status": "blocked",
                    "code": exc.error.code
                    if isinstance(exc, AgentFailure)
                    else "HOST_CONFIGURATION_ERROR",
                    "message": "Host operation failed safely; check configuration and grants",
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
