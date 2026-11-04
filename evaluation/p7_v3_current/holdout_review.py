"""Prepare private owner review material for the new 60-case revision, without Live."""

import argparse
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from openpyxl import load_workbook

from datapilot.datasets.repository import DatasetRepository
from datapilot.ingestion.common import digest
from datapilot.rag.parsing import decode
from datapilot.semantics.contracts import MetricRequest
from datapilot.semantics.repository import MetricRepository

from .candidate_binding import verify
from .holdout_contracts import compile_drafts
from .holdout_scoring import SCORER_VERSION


def load(path):
    return json.loads(path.read_bytes())


def raw_numeric(request, sheets):
    """Independent source-row calculation for the three revised native metric kinds."""
    kind = request["metric_id"]
    if kind == "active_subscriptions":
        point = request["as_of"]
        return Decimal(
            sum(
                r["start_date"] <= point and (r["end_date"] is None or r["end_date"] > point)
                for r in sheets["subscriptions"]
            )
        )
    start, end = (request["window"][k] for k in ("start", "end_exclusive"))
    if kind == "paid_invoice_revenue":
        return sum(
            (
                Decimal(str(r["amount_cents"])) / 100
                for r in sheets["invoices"]
                if start <= r["invoice_date"] < end
                and r["payment_status"] == "paid"
                and r["currency"] == "CNY"
            ),
            Decimal(0),
        )
    if kind == "usage" and request["metric_version"] == 3:
        return Decimal(
            sum(r["event_count"] for r in sheets["usage_events"] if start <= r["event_date"] < end)
        )
    raise ValueError("Revised metric needs an independently reviewed raw-row oracle")


def prepare(root, pack, candidate_path, candidate_sha256, environment, output):
    from final50_admission import isolated_reader
    from v3_oracle import ASOF, WINDOWS, query

    candidate = verify(root, candidate_path, candidate_sha256)
    revision = pack / "revision-01"
    manifest = load(revision / "manifest-v2.json")
    for name, sha in manifest["sha256"].items():
        path = revision / name.replace("\\", "/")
        if not path.resolve().is_relative_to(revision.resolve()):
            raise ValueError("Revision path escaped its pack")
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError("Authored revision drift")
    rows = [
        json.loads(line)
        for file in sorted((revision / "tasks").glob("*.jsonl"))
        for line in file.read_bytes().splitlines()
        if line.strip()
    ]
    originals = {
        row["id"]: row
        for file in sorted((pack / "tasks").glob("*.jsonl"))
        for line in file.read_bytes().splitlines()
        for row in [json.loads(line)]
    }
    receipts = load(revision / "revision-receipts.json")
    if len(receipts) != 11 or len({r["case_id"] for r in receipts}) != 11:
        raise ValueError("Expected exactly 11 distinct revised Gold reviews")
    bindings = load(pack / "bindings.json")
    task_bindings = load(pack / "private/task-bindings-v2.json")
    cases, reviews, metadata = compile_drafts(rows, bindings, task_bindings, receipts, candidate)
    by_id = {row["id"]: row for row in rows}
    case_by_id = {case.case_id: case for case in cases}
    source = pack / "sources/master.xlsx"
    if (
        hashlib.sha256(source.read_bytes()).hexdigest()
        != bindings["datasets"]["master"]["schema"]["source_sha256"]
    ):
        raise ValueError("Raw numeric source differs from its authorized source pin")
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        sheets = {}
        for sheet in workbook:
            values = iter(sheet.values)
            header = next(values)
            sheets[sheet.title] = [dict(zip(header, row, strict=True)) for row in values]
    finally:
        workbook.close()
    numeric = []
    for receipt in receipts:
        cid = receipt["case_id"]
        request = receipt["metric_request"]
        case = case_by_id[cid]
        raw_value = raw_numeric(request, sheets)
        expected = Decimal(by_id[cid]["oracle"]["expected_decimal"])
        repo = DatasetRepository(isolated_reader(environment, "UPLOAD_READER"), case.datasets)
        try:
            ctx = MetricRepository(repo).context(
                MetricRequest.model_validate_json(json.dumps(request))
            )
            if (ctx.metric_sha256, ctx.semantic_sha256, ctx.source_sha256) != (
                receipt["metric_sha256"],
                receipt["semantic_sha256"],
                receipt["source_sha256"],
            ):
                raise ValueError("Revised metric definition or source drift")
            temporal = request.get("window")
            with (
                patch.dict(
                    WINDOWS,
                    {cid: (temporal["start"], temporal["end_exclusive"])} if temporal else {},
                ),
                patch.dict(ASOF, {cid: request["as_of"]} if not temporal else {}),
            ):
                sql = query(
                    "master",
                    request["metric_id"],
                    request["metric_version"],
                    cid,
                    bindings["datasets"]["master"]["schema"],
                )
            result = repo.execute(request["dataset_id"], sql)
        finally:
            repo.close()
        db_value = Decimal(str(result.result.rows[0][0]))
        if not (raw_value == db_value == expected) or (
            result.query_sha256,
            result.result_sha256,
        ) != (receipt["query_sha256"], receipt["result_sha256"]):
            raise ValueError("Revised numeric Gold or original receipt cannot be reproduced")
        numeric.append(
            {
                "case_id": cid,
                "raw_decimal": format(raw_value, "f"),
                "pg_decimal": format(db_value, "f"),
                "authored_decimal": format(expected, "f"),
                "status": "THREE_WAY_MATCH",
                "receipt_reproduced": True,
                "original": originals[cid],
                "revised": by_id[cid],
                "metric_request": request,
                "pins": receipt,
                "semantic_gold_approval": "PENDING",
            }
        )
    fact_checks = []
    for row in rows:
        for fact in row.get("required_facts", []):
            text = decode((pack / "sources" / fact["group"] / fact["file"]).read_bytes())
            hint = fact.get("literal_hint")
            text_sha256 = hashlib.sha256(text.encode()).hexdigest()
            source = next(
                s
                for s in bindings["corpora"][fact["group"]]["manifest"]["sources"]
                if s["name"] == fact["file"]
            )
            if text_sha256 != source["text_sha256"]:
                raise ValueError("Document text differs from its authored source pin")
            fact_checks.append(
                {
                    "case_id": row["id"],
                    "fact_id": fact["fact_id"],
                    "text_sha256": text_sha256,
                    "literal_hint_occurrences": text.count(hint) if hint else 0,
                    "literal_hint": hint,
                    "authored_requirement": fact,
                    "goal_equivalence_approved": False,
                }
            )
    output.mkdir(parents=True, exist_ok=False)
    private = output / "private"
    private.mkdir()
    values = {
        "draft-inputs.jsonl": [c.model_dump(mode="json") for c in cases],
        "private/contract-review.json": reviews,
        "private/revised-gold-review.json": numeric,
        "private/fact-review.json": fact_checks,
    }
    for name, value in values.items():
        target = output / name
        if name.endswith(".jsonl"):
            target.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in value),
                encoding="utf-8",
            )
        else:
            target.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    review_text = [
        "# 新 60 题 revision-01：11 题 Gold 审阅\n",
        "数值三方复核不等于语义批准。逐题检查原题→修订题、保留的拒绝边界和文档要求。\n",
    ]
    for row in numeric:
        review_text += [
            f"## {row['case_id']}\n",
            f"原题：{row['original']['question']}\n",
            f"修订题：{row['revised']['question']}\n",
            "```json\n"
            + json.dumps(
                {
                    k: row[k]
                    for k in ("metric_request", "raw_decimal", "pg_decimal", "authored_decimal")
                }
                | {
                    "refusal_contract": row["revised"].get("refusal_contract"),
                    "required_facts": row["revised"].get("required_facts", []),
                    "original_oracle": row["original"].get("oracle"),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n```\n",
            "负责人结论：PENDING；不得据此派发。\n",
        ]
    (private / "OWNER-REVIEW.md").write_text("\n".join(review_text), encoding="utf-8")
    metadata.update(
        {
            "schema": "p7-new-holdout-review-preparation-1",
            "revised_numeric_rechecks": len(numeric),
            "numeric_status": "11_THREE_WAY_MATCH",
            "document_contract_reviews": sum(c.document_goal is not None for c in cases),
            "fact_checks": len(fact_checks),
            "literal_occurrence_counts": dict(
                Counter(str(r["literal_hint_occurrences"]) for r in fact_checks)
            ),
            "formal_launch_ready": False,
            "live_allowed": False,
            "paid_calls": 0,
            "files": {
                p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(output.rglob("*"))
                if p.is_file()
            },
            "private_bindings_sha256": digest(bindings),
            "host_scorer": {
                "version": SCORER_VERSION,
                "file": "evaluation/p7_v3_current/holdout_scoring.py",
                "sha256": candidate["files"]["evaluation/p7_v3_current/holdout_scoring.py"],
            },
            "revision_manifest_sha256": hashlib.sha256(
                (revision / "manifest-v2.json").read_bytes()
            ).hexdigest(),
        }
    )
    (output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("pack", "candidate", "environment", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--candidate-sha256", required=True)
    args = parser.parse_args()
    result = prepare(
        Path(__file__).resolve().parents[2],
        args.pack,
        args.candidate,
        args.candidate_sha256,
        load(args.environment),
        args.out,
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "planned",
                    "revised_numeric_rechecks",
                    "document_contract_reviews",
                    "fact_checks",
                    "live_allowed",
                    "paid_calls",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
