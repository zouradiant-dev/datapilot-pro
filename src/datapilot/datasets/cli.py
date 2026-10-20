"""Trusted local dataset selection. Read commands always use a real MCP subprocess."""

import asyncio
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetBinding, DatasetScope


def add_commands(subparsers):
    group = subparsers.add_parser(
        "datasets", help="Select a dataset/version, then query through MCP"
    )
    commands = group.add_subparsers(dest="dataset_command", required=True)
    listing = commands.add_parser(
        "list", help="List explicitly selected datasets; no wildcard scope"
    )
    listing.add_argument("--dataset", action="append", default=[])
    for name in ("schema", "query", "activate"):
        parser = commands.add_parser(name)
        parser.add_argument("dataset_id")
        parser.add_argument("--version", type=int, required=name == "activate")
        if name == "query":
            parser.add_argument("sql")


async def _read(args):
    from datapilot.runtime.mcp_client import dataset_session

    settings = Settings(llm_mode="fake")
    if not settings.upload_reader_database_url:
        raise AgentFailure("DATABASE_NOT_CONFIGURED", "Configure the upload reader identity")
    scope = DatasetScope(
        bindings=(
            [DatasetBinding(dataset_id=value) for value in args.dataset]
            if args.dataset_command == "list"
            else [DatasetBinding(dataset_id=args.dataset_id, version=args.version)]
        )
    )
    async with dataset_session(settings, scope) as tools:
        if args.dataset_command == "list":
            return await tools.listing()
        if args.dataset_command == "schema":
            return await tools.schema(args.dataset_id)
        return await tools.execute(args.dataset_id, args.sql)


def run(args) -> int:
    try:
        if args.dataset_command == "activate":
            from datapilot.db.management import management_url
            from datapilot.ingestion.service import IngestionService

            service = IngestionService(
                management_url("ingest"),
                storage_dir=Path(__file__).resolve().parents[3] / "artifacts/uploads/sources",
            )
            try:
                result = service.activate_version(
                    DatasetBinding(dataset_id=args.dataset_id, version=args.version)
                )
            finally:
                service.close()
        else:
            result = asyncio.run(_read(args))
        print(result.model_dump_json(indent=2))
        return 0
    except AgentFailure as exc:
        error = exc.error.model_dump()
    except (ValidationError, ValueError, OSError):
        error = {
            "code": "CONFIG_INVALID",
            "message": "Invalid dataset selection or configuration",
            "retryable": False,
        }
    print(json.dumps({"status": "failed", "error": error}), file=sys.stderr)
    return 2
