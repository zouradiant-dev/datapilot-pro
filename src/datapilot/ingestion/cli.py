"""Local preview/confirm commands only. No DB settings, keys, DDL or model calls."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from datapilot.ingestion.common import read_file, render_json
from datapilot.ingestion.confirmation import confirm_file
from datapilot.ingestion.contracts import (
    ConfirmationOverrides,
    ParseError,
    ParseFailure,
    ParseLimits,
    ParseOptions,
    SchemaProposal,
)
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema


def add_commands(subparsers) -> None:
    ingest = subparsers.add_parser(
        "ingest", help="Local file preview/confirmation; no database writes"
    )
    commands = ingest.add_subparsers(dest="ingest_command", required=True)
    preview = commands.add_parser("preview", help="Parse CSV/XLSX and propose a bounded schema")
    preview.add_argument("file", type=Path)
    preview.add_argument("--header", choices=("auto", "present", "absent"), default="auto")
    preview.add_argument("--encoding")
    preview.add_argument("--delimiter", choices=(",", ";", "|", "tab"))
    preview.add_argument("--sheet", action="append", dest="sheets")
    preview.add_argument("--max-file-bytes", type=int, default=10 * 1024**2)
    preview.add_argument("--max-rows", type=int, default=100_000)
    preview.add_argument("--max-columns", type=int, default=100)
    preview.add_argument("--max-sheets", type=int, default=10)
    preview.add_argument("--max-uncompressed-bytes", type=int, default=64 * 1024**2)
    preview.add_argument("--output", type=Path)
    confirm = commands.add_parser("confirm", help="Reparse source and validate reviewed overrides")
    confirm.add_argument("file", type=Path)
    confirm.add_argument("--proposal", type=Path, required=True)
    confirm.add_argument("--overrides", type=Path)
    confirm.add_argument(
        "--reviewed", action="store_true", help="Explicitly acknowledge preview and warnings"
    )
    confirm.add_argument("--output", type=Path)


def run(args: argparse.Namespace) -> int:
    try:
        if args.ingest_command == "preview":
            limits = ParseLimits(
                max_file_bytes=args.max_file_bytes,
                max_total_rows=args.max_rows,
                max_columns=args.max_columns,
                max_sheets=args.max_sheets,
                max_uncompressed_bytes=args.max_uncompressed_bytes,
            )
            options = ParseOptions(
                header=args.header,
                encoding=args.encoding,
                delimiter="\t" if args.delimiter == "tab" else args.delimiter,
                sheets=args.sheets,
            )
            result = propose_schema(parse_file(args.file, options=options, limits=limits))
        else:
            proposal = SchemaProposal.model_validate_json(read_file(args.proposal, 4 * 1024**2))
            limits = proposal.limits
            overrides = (
                ConfirmationOverrides.model_validate_json(read_file(args.overrides, 1024**2))
                if args.overrides
                else None
            )
            result = confirm_file(args.file, proposal, reviewed=args.reviewed, overrides=overrides)
        text = render_json(result, limits.max_preview_bytes)
        if args.output:
            try:
                with args.output.open("x", encoding="utf-8") as stream:
                    stream.write(text + "\n")
            except FileExistsError as exc:
                raise ParseFailure(
                    "OUTPUT_EXISTS", "Output already exists; choose a new filename"
                ) from exc
        else:
            print(text)
        return 0
    except ParseFailure as exc:
        error = exc.error
    except ValidationError:
        error = ParseError(
            code="CONFIG_INVALID", message="Options/proposal/overrides violate the input contract"
        )
    except OSError:
        error = ParseError(code="FILE_UNWRITABLE", message="Cannot write the selected output file")
    print(
        json.dumps(
            {"status": "failed", "error": error.model_dump(exclude_none=True)}, ensure_ascii=False
        ),
        file=sys.stderr,
    )
    return 2
