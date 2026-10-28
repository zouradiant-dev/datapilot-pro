"""Prepare and seal a private business pack. Never runs a candidate or writes a database."""

import argparse
import csv
import io
import json
import re
import secrets
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from p7_holdout_oracle import oracle, reference_sql
from p7_holdout_pack import (
    CaseInput,
    Gold,
    canonical,
    input_leakage,
    old_question_inputs,
    seal,
    sha,
    validate_inputs,
)
from p7_isolated_pg import environment, inspect

from datapilot.config import Settings
from datapilot.ingestion.common import digest
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ConfirmationOverrides, ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.persistence.session import run_async
from datapilot.rag.contracts import Chunker, IndexManifest, Limits, Target
from datapilot.rag.models import checked_file, specification
from datapilot.rag.parsing import parse_sources
from datapilot.runtime.mcp_client import database_session
from datapilot.semantics.contracts import MetricDraft, SemanticDraft

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/p7/business-holdout"
FIELDS = {
    "invoices": {
        "record_id": "invoice_id",
        "amount": "amount",
        "invoice_date": "invoice_date",
        "payment_status": "payment_status",
        "currency": "currency",
    },
    "subscriptions": {
        "record_id": "subscription_id",
        "customer_id": "customer_id",
        "start_date": "start_date",
        "end_date": "end_date",
        "termination_kind": "termination_kind",
    },
    "usage_events": {
        "record_id": "event_id",
        "event_date": "event_date",
        "event_count": "event_count",
        "feature": "feature",
    },
}


def write_source(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".csv":
        rows = next(iter(records.values()))
        with path.open("x", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        return
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.properties.created = workbook.properties.modified = datetime(2023, 1, 1)
    for name, rows in records.items():
        sheet = workbook.create_sheet(name)
        sheet.append(list(rows[0]))
        for row in rows:
            sheet.append(list(row.values()))
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    with ZipFile(io.BytesIO(buffer.getvalue())) as source, ZipFile(path, "x") as target:
        for name in sorted(source.namelist()):
            info = ZipInfo(name, date_time=(2023, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            content = source.read(name)
            if name == "docProps/core.xml":
                content = re.sub(
                    rb"(<dcterms:modified[^>]*>).*?(</dcterms:modified>)",
                    rb"\g<1>2023-01-01T00:00:00Z\2",
                    content,
                )
            target.writestr(info, content)


def prepare_datasets(spec, stage):
    pins, confirmations = {}, {}
    for alias, data in spec["datasets"].items():
        entity = next(iter(data["records"]))
        filename = "snapshot.xlsx" if data["format"] == "xlsx" else entity + ".csv"
        path = stage / "datasets" / alias / filename
        write_source(path, data["records"])
        parsed = parse_file(path, options=ParseOptions(header="present"))
        overrides = []
        for table in parsed.tables:
            for column in table.columns:
                name = column.normalized_name
                if name.endswith("_date"):
                    overrides.append(
                        {"table_id": table.table_id, "column": name, "logical_type": "DATE"}
                    )
        confirmation = confirm_schema(
            parsed,
            propose_schema(parsed),
            reviewed=True,
            overrides=ConfirmationOverrides.model_validate_json(
                json.dumps(
                    {"columns": overrides, "primary_keys": {t.table_id: [] for t in parsed.tables}}
                )
            ),
        )
        name = "p7-bh2-" + str(spec["seed"]) + "-" + data["name"]
        identifier = str(uuid5(NAMESPACE_URL, "datapilot:local:" + name))
        by_entity = {}
        for table in parsed.tables:
            key = table.source_name if table.source_name in data["records"] else entity
            expected = data["records"][key]
            # CSV has no native null cell: DictWriter encodes None as the empty field.
            null_cell = "" if data["format"] == "csv" else None
            expected_rows = [
                [null_cell if r[k] is None else str(r[k]) for k in r] for r in expected
            ]
            if table.rows != expected_rows:
                raise ValueError("Source serialization/parser changed the declared original rows")
            by_entity[key] = table.table_id
        pins[alias] = {
            "dataset_id": identifier,
            "dataset_version": data["version"],
            "import_name": name,
            "asset_path": str(path.relative_to(stage)).replace("\\", "/"),
            "source_sha256": sha(path.read_bytes()),
            "confirmation_sha256": confirmation.confirmation_sha256,
            "status": "planned_not_registered",
            "table_ids": by_entity,
            "semantic_definitions": [],
            "metric_definitions": [],
        }
        confirmations[alias] = confirmation.model_dump(mode="json")
    return pins, confirmations


def bind_metric(ref, spec, pin, definitions):
    data = spec["datasets"][ref["dataset"]]
    unconfirmed = ref.get("unconfirmed_amount", False)
    semantic_version = 2 if unconfirmed else 1
    entities = []
    for entity, fields in FIELDS.items():
        if entity not in data["records"]:
            continue
        mapping = {
            "entity": entity,
            "table_id": pin["table_ids"][entity],
            "fields": fields,
            "grain": [fields["record_id"]],
            "coverage_start": data["coverage"][0],
            "coverage_end_exclusive": data["coverage"][1],
        }
        if entity == "invoices":
            mapping["amount_storage"] = None if unconfirmed else data.get("amount_storage")
        if entity == "subscriptions":
            mapping.update(
                history_complete=data["history_complete"], subscription_identity="contract"
            )
        entities.append(mapping)
    semantic = SemanticDraft.model_validate_json(
        json.dumps(
            {
                "dataset_id": pin["dataset_id"],
                "dataset_version": pin["dataset_version"],
                "entities": entities,
            }
        )
    )
    semantics = {
        "semantic_version": semantic_version,
        "sha256": digest(semantic),
        "definition": semantic.model_dump(mode="json"),
        "review_state": "proposed_synthetic_spec",
    }
    if semantics not in pin["semantic_definitions"]:
        pin["semantic_definitions"].append(semantics)
    draft = MetricDraft(
        dataset_id=pin["dataset_id"],
        dataset_version=pin["dataset_version"],
        semantic_version=semantic_version,
        metric_id=ref["metric_id"],
        currency=ref["currency"],
        feature=ref.get("feature"),
    )
    key = (pin["dataset_id"], pin["dataset_version"], draft.metric_id, digest(draft))
    if key not in definitions:
        version = 1 + sum(k[:3] == key[:3] for k in definitions)
        definitions[key] = version
        pin["metric_definitions"].append(
            {
                "metric_id": draft.metric_id,
                "metric_version": version,
                "semantic_version": semantic_version,
                "sha256": digest(draft),
                "definition": draft.model_dump(mode="json"),
                "review_state": "proposed_synthetic_spec",
            }
        )
    policy = {
        "metric_id": ref["metric_id"],
        "currency": ref["currency"],
        "feature": ref.get("feature"),
        "coverage": data["coverage"],
        "amount_storage": None if unconfirmed else data.get("amount_storage"),
        "history_complete": data["history_complete"],
        "reference_join": ref.get("reference_join", False),
    }
    request = {
        "dataset_id": pin["dataset_id"],
        "dataset_version": pin["dataset_version"],
        "semantic_version": semantic_version,
        "metric_id": draft.metric_id,
        "metric_version": definitions[key],
        "window": {"start": ref["window"][0], "end_exclusive": ref["window"][1]}
        if ref["window"]
        else None,
        "as_of": ref["as_of"],
    }
    return request, policy


def prepare_documents(spec, stage, datasets):
    chunker = Chunker()
    model = specification()
    for name in model.files:
        checked_file(name)  # Hash-only; never fetch or run a retrieval query.
    groups = {
        "old": ("cash_v1", [k for k in spec["docs"] if k not in {"precision", "foreign"}]),
        "new": ("cash_v1", [k for k in spec["docs"] if k not in {"precision", "foreign"}]),
        "data_v2": ("cash_v2", [k for k in spec["docs"] if k not in {"precision", "foreign"}]),
        "precision": ("precision", ["precision"]),
        "foreign": ("cash_v1", ["foreign"]),
    }
    result = {}
    for group, (dataset, keys) in groups.items():
        corpus_name = "cash" if group in {"old", "new"} else group
        corpus_id = str(uuid5(NAMESPACE_URL, "p7-bh2-corpus:" + str(spec["seed"]) + corpus_name))
        paths = []
        facts = {}
        specs = {}
        for key in keys:
            item = (
                spec["billing_v2"]
                if key == "billing" and group in {"new", "data_v2"}
                else spec["docs"][key]
            )
            filename, text, literals = item
            path = stage / "documents" / group / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode())
            paths.append(path)
            specs[filename] = (
                "billing_new" if key == "billing" and group in {"new", "data_v2"} else key,
                literals,
            )
        parsed = parse_sources(paths, corpus_id, chunker, Limits())
        target = Target(
            corpus_id=corpus_id,
            owner=spec["owner"] if group != "foreign" else "another-owner",
            dataset_id=datasets[dataset]["dataset_id"]
            if group in {"precision", "data_v2"}
            else None,
            dataset_version=datasets[dataset]["dataset_version"]
            if group in {"precision", "data_v2"}
            else None,
        )
        manifest = IndexManifest(
            target=target,
            model=model,
            chunker=chunker,
            sources=sorted((p.info for p in parsed), key=lambda p: p.source_id),
        )
        version = digest(manifest)
        for source in parsed:
            key, literals = specs[source.info.name]
            for number, literal_text in enumerate(literals):
                start = source.text.index(literal_text)
                end = start + len(literal_text)
                chunks = [
                    c.model_dump(mode="json")
                    for c in source.info.chunks
                    if c.start <= start and c.end >= end
                ]
                if not chunks:
                    raise ValueError(
                        "An independent Gold fact must be locatable in a full authorized chunk"
                    )
                facts[f"{key}:{number}"] = {
                    "source_id": source.info.source_id,
                    "document_id": source.info.document_id,
                    "version": source.info.version,
                    "source_sha256": source.info.version,
                    "start": start,
                    "end": end,
                    "literal": literal_text,
                    "chunks": chunks,
                }
        result[group] = {
            "status": "planned_not_indexed",
            "manifest": manifest.model_dump(mode="json"),
            "index_version": version,
            "dataset_alias": dataset,
            "facts": facts,
        }
    return result


def document_goal(case, corpora, pins):
    if case["lane"] == "sql_only":
        return None, None, None
    snap = case["snapshot"]
    group = (
        case["corpus"]
        if case["corpus"] != "cash"
        else "new"
        if snap == "new"
        else "data_v2"
        if snap == "data_v2"
        else "old"
    )
    corpus = corpora[group]
    manifest = corpus["manifest"]
    sources = manifest["sources"]
    selectors = {
        "single": ["onboarding.md"],
        "near": ["near-miss.md"],
        "billing_only": ["billing.md"],
        "june": ["june-only.md"],
        "history": ["history.md"],
    }
    chosen = [s for s in sources if s["name"] in selectors[snap]] if snap in selectors else sources
    target = manifest["target"]
    scope = {
        "owner": case["owner"],
        "corpora": [
            {
                "corpus_id": target["corpus_id"],
                "index_version": corpus["index_version"],
                "document_ids": [s["document_id"] for s in chosen],
            }
        ],
        "datasets": {
            "bindings": [
                {
                    "dataset_id": pins[corpus["dataset_alias"]]["dataset_id"],
                    "version": pins[corpus["dataset_alias"]]["dataset_version"],
                }
            ]
        },
        "min_score": 0.55,
        "allow_saas": target["dataset_id"] is None,
    }
    facts = [corpus["facts"][f] for f in case["facts"]]
    if any(f["document_id"] not in scope["corpora"][0]["document_ids"] for f in facts):
        raise ValueError("Gold fact is outside its authorized source closure")
    retrieval = {
        "disposition": case["retrieval"],
        "minimum_distinct_sources": case["min_sources"],
        "facts": facts,
        "relevant_source_ids": sorted({f["source_id"] for f in facts}),
        "relevant_document_ids": sorted({f["document_id"] for f in facts}),
        "relevant_chunk_ids": sorted({c["chunk_id"] for f in facts for c in f["chunks"]}),
        "retrieval_success_does_not_verify_business_conclusion": True,
    }
    return (
        {"goal_id": "documents", "question": case["question"], "metric_goals": []},
        scope,
        retrieval,
    )


async def prepare(author_spec, destination):
    author_spec, destination = author_spec.resolve(), destination.resolve()
    if not author_spec.resolve().is_relative_to(
        (ROOT / "artifacts").resolve()
    ) or not destination.resolve().is_relative_to(BASE.resolve()):
        raise ValueError("Private authoring and sealed pack must remain under project artifacts")
    spec = json.loads(author_spec.read_text(encoding="utf-8"))
    stage = destination.parent / (destination.name + "-draft-assets")
    if stage.exists() or destination.exists():
        raise ValueError("Preserve prior drafts/seals; do not silently regenerate")
    pins, confirmations = prepare_datasets(spec, stage)
    corpora = prepare_documents(spec, stage, pins)
    definitions = {}
    inputs = []
    gold = []
    numeric_jobs = []
    for item in spec["cases"]:
        item = dict(item, owner=spec["owner"])
        requests = []
        expected = []
        bindings = {}
        for i, ref in enumerate(item["metrics"], 1):
            pin = pins[ref["dataset"]]
            request, policy = bind_metric(ref, spec, pin, definitions)
            request["goal_id"] = f"metric_{i}"
            result = oracle(spec["datasets"][ref["dataset"]]["records"], policy, request)
            if not item["denied"] and not item["confirmation"]:
                expected.append(dict(goal_id=request["goal_id"], **result))
                if result["disposition"] == "verified":
                    numeric_jobs.append(
                        (
                            item["case_id"],
                            request["goal_id"],
                            ref["dataset"],
                            policy,
                            request,
                            result,
                        )
                    )
            bindings[pin["dataset_id"]] = pin["dataset_version"]
            requests.append(request)
        if item["denied"]:
            bindings = {pins["cash_v1"]["dataset_id"]: 1}
        if item["confirmation"]:
            field = "dataset_version" if item["lane"] == "sql_rag" else "metric_version"
            requests[0][field] = 999999
        doc, rag, retrieval = document_goal(item, corpora, pins)
        if doc:
            doc["metric_goals"] = [r["goal_id"] for r in requests]
        if rag:
            for binding in rag["datasets"]["bindings"]:
                bindings[binding["dataset_id"]] = binding["version"]
        inputs.append(
            CaseInput.model_validate_json(
                json.dumps(
                    {
                        "case_id": item["case_id"],
                        "lane": item["lane"],
                        "objective": item["objective"],
                        "question": item["question"],
                        "owner": spec["owner"],
                        "metrics": requests,
                        "document_goal": doc,
                        "rag_scope": rag,
                        "causal_requested": item["causal"],
                        "datasets": {
                            "bindings": [
                                {"dataset_id": k, "version": v} for k, v in bindings.items()
                            ]
                        },
                    }
                )
            )
        )
        refusals = [r["reason"] for r in expected if r.get("reason")]
        if item["denied"]:
            refusals.append("host_scope_denied")
        if item["confirmation"]:
            refusals.append("version_confirmation_required")
        if retrieval and retrieval["disposition"] != "complete":
            refusals.append("document_evidence_insufficient")
        if item["causal"]:
            refusals.append("causal_effect_not_identified")
        gold.append(
            Gold.model_validate_json(
                json.dumps(
                    {
                        "case_id": item["case_id"],
                        "business_completion": item["business_completion"],
                        "host_decision": "permission_denied"
                        if item["denied"]
                        else "confirmation_required"
                        if item["confirmation"]
                        else "review_then_run",
                        "metrics": expected,
                        "retrieval": retrieval,
                        "refusal_conditions": refusals,
                        "causal_claim_must_remain_unverified": item["causal"],
                    }
                )
            )
        )
    validate_inputs(inputs)
    # Only question strings and source fingerprints are selected. No old Gold is supplied
    # to any candidate (none is constructed) or used to choose this pack's answers.
    old = []
    for name in [
        "tests/fixtures/evaluation/business-dev.jsonl",
        "tests/fixtures/evaluation/intent-dev.jsonl",
        "artifacts/p7/sealed/intent-holdout.jsonl",
    ]:
        old.extend(old_question_inputs((ROOT / name).read_bytes()))
    old_hashes = []
    for folder in ["tests/fixtures/semantics", "tests/fixtures/rag", "tests/fixtures/reporting"]:
        old_hashes.extend(sha(p.read_bytes()) for p in (ROOT / folder).iterdir() if p.is_file())
    assets = {
        str(p.relative_to(stage)).replace("\\", "/"): p.read_bytes()
        for p in stage.rglob("*")
        if p.is_file()
    }
    leakage = input_leakage(
        inputs,
        old,
        old_source_hashes=old_hashes,
        new_source_hashes=[sha(v) for v in assets.values()],
    )
    if any(
        leakage[k]
        for k in [
            "exact_question_overlap",
            "numeric_normalized_question_overlap",
            "near_duplicate_warnings",
            "source_byte_overlap",
        ]
    ):
        raise ValueError("New author pack failed input/source independence checks")
    inspect()
    env = environment()
    settings = Settings(
        llm_mode="fake", _env_file=None, reader_database_url=env["DATAPILOT_READER_DATABASE_URL"]
    )
    proofs = []
    cache = {}
    async with database_session(settings) as tools:
        for case_id, goal_id, alias, policy, request, expected in numeric_jobs:
            query = reference_sql(spec["datasets"][alias]["records"], policy, request)
            if query not in cache:
                cache[query] = await tools.execute(query)
            result = cache[query]
            if result.truncated or result.row_count != 1:
                raise ValueError("Reference oracle result shape differs")
            actual = dict(zip(result.columns, result.rows[0], strict=True))
            if "numerator" in expected:
                agrees = (
                    int(actual["numerator"]) == expected["numerator"]
                    and int(actual["denominator"]) == expected["denominator"]
                )
            else:
                agrees = Decimal(str(actual["value"])) == Decimal(expected["value"])
            if not agrees:
                raise ValueError("Independent Python/PostgreSQL Gold disagreement")
            proofs.append(
                {
                    "case_id": case_id,
                    "goal_id": goal_id,
                    "query_sha256": digest(query),
                    "result_sha256": digest(result),
                    "reference_uses_join": " JOIN " in query,
                    "agrees": True,
                }
            )
    proof = {
        "status": "passed",
        "database_writes": 0,
        "physical_business_tables_read": 0,
        "transport": "real_PG17_readonly_MCP_literal_CTEs",
        "unique_queries": len(cache),
        "numeric_goals": len(proofs),
        "checks": proofs,
        "candidate_executions": 0,
        "paid_calls": 0,
    }
    baseline = json.loads((BASE / "baseline.json").read_text(encoding="utf-8"))
    for name, expected in baseline["files"].items():
        if sha((ROOT / name).read_bytes()) != expected:
            raise ValueError("Frozen production code changed")
    freeze = {
        "base_commit": baseline["head"],
        "production_files": baseline["files"],
        "preparation_files": {
            n: sha((ROOT / n).read_bytes())
            for n in [
                "scripts/p7_holdout_oracle.py",
                "scripts/p7_holdout_pack.py",
                "scripts/prepare_p7_business_holdout.py",
            ]
        },
        "candidate_tuning": False,
    }
    archive_pins = {
        "datasets": pins,
        "confirmations": confirmations,
        "corpora": {
            k: {key: value for key, value in v.items() if key != "facts"}
            for k, v in corpora.items()
        },
        "all_catalogs_materialized": False,
        "source_review_required_before_live": True,
    }
    marker = seal(
        destination,
        inputs=inputs,
        gold=gold,
        assets=assets,
        pins=archive_pins,
        leakage=leakage,
        proof=proof,
        freeze=freeze,
        canary=secrets.token_hex(24),
    )
    public = {
        "schema_version": "p7-independent-business-holdout-1",
        "sealed_at": datetime.now(UTC).isoformat(),
        "base_commit": baseline["head"],
        "status": "sealed_not_live_ready",
        "tasks": len(inputs),
        "lane_counts": dict(Counter(i.lane for i in inputs)),
        "pack_path": str(destination.relative_to(ROOT)).replace("\\", "/"),
        "seal_sha256": sha(canonical(marker)),
        "inputs_sha256": marker["files"]["inputs.jsonl"],
        "gold_sha256": marker["files"]["gold.jsonl"],
        "source_assets": {k: sha(v) for k, v in assets.items()},
        "dataset_pins": [
            {
                k: p[k]
                for k in [
                    "dataset_id",
                    "dataset_version",
                    "source_sha256",
                    "confirmation_sha256",
                    "status",
                ]
            }
            for p in pins.values()
        ],
        "corpus_pins": [
            {
                "corpus_id": p["manifest"]["target"]["corpus_id"],
                "index_version": p["index_version"],
                "status": p["status"],
                "model": p["manifest"]["model"],
                "chunker": p["manifest"]["chunker"],
            }
            for p in corpora.values()
        ],
        "leakage": leakage,
        "oracle_proof_summary": {k: v for k, v in proof.items() if k != "checks"},
        "live_allowed": False,
        "holdout_candidate_results": "not_run",
        "production_code_unchanged": True,
        "gold_human_review": "pending",
        "actual_registry_and_vector_materialization": "pending_fresh_isolated_instance",
        "planned_live_runner_and_trusted_evidence_collector": "pending_separate_execution_gate",
    }
    output = ROOT / "docs/research/p7-independent-business-holdout.json"
    with output.open("x", encoding="utf-8") as stream:
        json.dump(public, stream, ensure_ascii=False, indent=2)
    print(
        json.dumps(
            {
                "tasks": len(inputs),
                "lanes": public["lane_counts"],
                "status": public["status"],
                "oracle": public["oracle_proof_summary"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--author-spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run_async(prepare(args.author_spec, args.output))
