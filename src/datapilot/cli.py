"""Separate infrastructure, migration, seed, health and runtime commands."""

import argparse
import asyncio
import json
import sys

from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from datapilot.config import Settings


def json_default(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser(description="DataPilot Pro / PostgreSQL + CSV/XLSX preview")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("db-init", help="Admin: create roles, schemas and pgvector")
    sub.add_parser("migrate", help="Owner: Alembic upgrade head, then grant exact business tables")
    seed = sub.add_parser("seed", help="Seed role: insert fixed data into an EMPTY database")
    seed.add_argument("--seed", type=int, default=42)
    seed.add_argument("--customers", type=int, default=240)
    from datapilot.ingestion.cli import add_commands

    add_commands(sub)
    from datapilot.datasets.cli import add_commands as add_dataset_commands

    add_dataset_commands(sub)
    from datapilot.semantics.cli import add_commands as add_semantic_commands

    add_semantic_commands(sub)
    sub.add_parser("health", help="Reader: verify PostgreSQL 17, extension, permissions and seed")
    query = sub.add_parser("ask", help="Supervisor -> SQL -> MCP -> PostgreSQL -> Answer")
    query.add_argument("question")
    query.add_argument("--mode", choices=("live", "fake"))
    query.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        if args.command == "ingest":
            from datapilot.ingestion.cli import run

            return run(args)
        elif args.command == "datasets":
            from datapilot.datasets.cli import run

            return run(args)
        elif args.command == "semantics":
            from datapilot.semantics.cli import run

            return run(args)
        elif args.command == "db-init":
            from datapilot.db.management import initialize

            initialize()
            result = {"status": "initialized"}
        elif args.command == "migrate":
            from datapilot.db.management import grant_business_access, migrate, migration_head

            migrate()
            grant_business_access()
            result = {"status": "migrated", "revision": migration_head()}
        elif args.command == "seed":
            from datapilot.data.generator import generate_dataset, seed_database
            from datapilot.db.management import management_url

            result = seed_database(
                management_url("seed"), generate_dataset(seed=args.seed, customers=args.customers)
            )
        elif args.command == "health":
            from datapilot.db.health import database_health

            settings = Settings(llm_mode="fake")
            if not settings.reader_database_url:
                raise ValueError("Configure reader URL")
            result = database_health(
                settings.reader_database_url.get_secret_value(),
                upload_reader_url=(
                    settings.upload_reader_database_url.get_secret_value()
                    if settings.upload_reader_database_url
                    else None
                ),
            )
        else:
            from datapilot.graph import run_question

            settings = Settings(**({"llm_mode": args.mode} if args.mode else {}))
            result = asyncio.run(run_question(settings, args.question, include_artifacts=args.json))
            if not args.json:
                print(f"mode={result['mode']} status={result['status']}\n" + result["answer"])
                return 0 if result["status"] == "succeeded" else 2
        print(json.dumps(result, default=json_default, ensure_ascii=False, indent=2))
        return 0 if result.get("status") != "failed" else 2
    except (ValidationError, ValueError, OSError, SQLAlchemyError):
        print(
            "Configuration/database error: check .env, role permissions, migration and health.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
