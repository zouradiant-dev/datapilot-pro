"""Single publication of independent input/Gold, protocol and layered implementation seals."""

import json
import re
import shutil
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from p7_holdout_pack import input_leakage, normalized_question, old_question_inputs
from v3_common import (
    BASE,
    BUDGET,
    CAMPAIGN,
    OWNER,
    PACK,
    PROFILE,
    ROOT,
    canonical,
    clean_settings,
    expected_order,
    file_map,
    infrastructure,
    parent_freeze,
    scope,
    sha,
    write_new,
)
from v3_oracle import query
from v3_prepare import build_cases
from v3_runner import authority

from datapilot.datasets.contracts import DatasetScope
from datapilot.ingestion.common import digest
from datapilot.persistence.session import run_async
from datapilot.runtime.mcp_client import dataset_session


def leakage(tasks, pins):
    old_paths = [
        ROOT / "tests/fixtures/evaluation/business-dev.jsonl",
        ROOT / "tests/fixtures/evaluation/intent-dev.jsonl",
        ROOT / "artifacts/p7/business-holdout/sealed-business-final/inputs.jsonl",
        ROOT / "artifacts/p7/dev-smoke-v1/sealed/inputs.jsonl",
    ]
    # Include consumed intent Holdout question inputs, never its expected answers.
    intent = ROOT / "artifacts/p7/sealed/intent-holdout.jsonl"
    if intent.exists():
        old_paths.append(intent)
    old = []
    for path in old_paths:
        if not path.is_file():
            raise ValueError("Missing comparison input: " + str(path))
        old.extend(old_question_inputs(path.read_bytes()))
    old_hashes = []
    for directory in [
        ROOT / "artifacts/p7/business-holdout/sealed-business-final/assets",
        ROOT / "artifacts/p7/dev-smoke-v1/sealed/assets",
    ]:
        old_hashes.extend(sha(p.read_bytes()) for p in directory.rglob("*") if p.is_file())
    new_hashes = [sha(p.read_bytes()) for p in (BASE / "sources").rglob("*") if p.is_file()]
    result = input_leakage(tasks, old, old_source_hashes=old_hashes, new_source_hashes=new_hashes)

    # Additional deterministic normalization removes proper-name and calendar presentation changes.
    def structural(text):
        text = normalized_question(text)
        text = re.sub(r"澄岳|北辰|合成\s*SaaS|人民币|CNY", "", text, flags=re.I)
        return re.sub(r"[\W_]+", "", text)

    previous = {structural(row["question"]) for row in old}
    result["proper_name_calendar_normalized_overlap"] = [
        t.case_id for t in tasks if structural(t.question) in previous
    ]
    result["comparison_files"] = [p.relative_to(ROOT).as_posix() for p in old_paths]
    result["common_business_primitives_reused"] = [
        "closed P3 metrics",
        "zero cohort / duplicate / NULL safety contracts",
        "source-version and authorization contracts",
    ]
    result["gold_logic_claim"] = (
        "Source and task objectives are newly authored; clo"
        "sed formula/refusal primitives are intentionally s"
        "hared, not novel independent algorithms or third-p"
        "arty blind authorship."
    )
    result["independent_customer_distribution"] = False
    return result


async def physical_pins_and_oracle(values, pins, tasks, golds, specs):
    settings = clean_settings(values)
    for row in pins["datasets"].values():
        row["table_snapshots"] = await versioned_snapshots(settings, row)
    previous = json.loads((BASE / "oracle-proof.json").read_bytes())
    checked = []
    by_id = {t.case_id: t for t in tasks}
    for old in previous["independent_sql_decimal_checks"]:
        task = by_id[old["case_id"]]
        gold = next(g for g in golds if g.case_id == task.case_id)
        index = next(i for i, m in enumerate(task.metrics) if m.goal_id == old["goal_id"])
        spec = specs[task.case_id][index]
        expected = gold.metrics[index]
        row = dict(old)
        row["unit"] = expected.unit
        request = task.metrics[index]
        if spec[0] == "future":
            binding = pins["datasets"]["future"]
            async with dataset_session(
                settings, DatasetScope.model_validate_json(json.dumps(binding["scope"]))
            ) as tool:
                result = await tool.execute(request.dataset_id, query(*spec, binding["schema"]))
            if str(result.result.rows[0][0]) != expected.value:
                raise ValueError("Revised physical version Oracle mismatch")
            row.update(query_sha256=result.query_sha256, result_sha256=result.result_sha256)
        row.update(
            request_sha256=digest(request),
            dataset_id=request.dataset_id,
            dataset_version=request.dataset_version,
            source_sha256=pins["datasets"][spec[0]]["schema"]["source_sha256"],
        )
        checked.append(row)
    # Independent real multi-table checks; these do not grant arbitrary JOIN to the Metric Worker.
    master = pins["datasets"]["master"]
    tables = {t["source_name"]: '"' + t["physical_name"] + '"' for t in master["schema"]["tables"]}
    queries = [
        f"SELECT COUNT(*) AS n FROM {tables['invoices']} i "
        f"JOIN {tables['customers']} c ON i.customer_id=c.customer_id",
        f"SELECT COUNT(*) AS n FROM {tables['invoices']} i "
        f"JOIN {tables['subscriptions']} s ON i.subscription_id=s.subscription_id "
        "AND i.customer_id=s.customer_id",
        f"SELECT COUNT(*) AS n FROM {tables['payments']} p LEFT JOIN {tables['invoices']} i "
        "ON p.invoice_id=i.invoice_id WHERE i.invoice_id IS NULL",
        f"SELECT COUNT(*) AS n FROM {tables['refunds']} r LEFT JOIN {tables['invoices']} i "
        "ON r.invoice_id=i.invoice_id WHERE i.invoice_id IS NULL",
    ]
    joins = []
    async with dataset_session(
        settings, DatasetScope.model_validate_json(json.dumps(master["scope"]))
    ) as tool:
        for sql, expected in zip(queries, [24, 24, 0, 0], strict=True):
            result = await tool.execute(master["schema"]["dataset_id"], sql)
            if result.result.truncated or result.result.rows != [[expected]]:
                raise ValueError("Independent relation/grain audit failed")
            joins.append(
                {
                    "query_sha256": result.query_sha256,
                    "result_sha256": result.result_sha256,
                    "expected": expected,
                    "actual": expected,
                }
            )
    return {
        "status": "passed",
        "numeric_checks": checked,
        "multi_table_relation_checks": joins,
        "models_called": 0,
        "gold_numeric_source": (
            "independent source Decimal and actual scoped PG SQL; never candidate output"
        ),
    }


async def versioned_snapshots(settings, binding):
    """The historical Smoke helper intentionally pins v1; new fixtures include explicit v2."""
    snapshots = {}
    async with dataset_session(
        settings, DatasetScope.model_validate_json(json.dumps(binding["scope"]))
    ) as tool:
        schema = binding["schema"]
        for table in schema["tables"]:
            if table["row_count"] > 100:
                raise ValueError("Bounded mechanical fingerprint only")
            column = table["columns"][0]["normalized_name"]
            sql = f'SELECT * FROM "{table["physical_name"]}" ORDER BY "{column}"'
            result = await tool.execute(schema["dataset_id"], sql)
            if result.result.truncated or result.result.row_count != table["row_count"]:
                raise ValueError("Incomplete physical fingerprint")
            snapshots[table["table_id"]] = {"sql": sql, "result_sha256": result.result_sha256}
    return snapshots


def main():
    if PACK.exists() or (BASE / "anchor.json").exists():
        raise ValueError("Never overwrite or reseal")
    values = infrastructure(ROOT / "artifacts/p7/unified-regression/private/environment.json")
    parent, product = parent_freeze()
    pins = json.loads((BASE / "bindings-v2.json").read_bytes())
    tasks, golds, specs = build_cases(pins)
    report = leakage(tasks, pins)
    for field in [
        "exact_question_overlap",
        "numeric_normalized_question_overlap",
        "source_byte_overlap",
        "near_duplicate_warnings",
        "proper_name_calendar_normalized_overlap",
    ]:
        if report[field]:
            raise ValueError("Independence audit requires resolution: " + field)
    if (BASE / "independence.json").exists():
        if json.loads((BASE / "independence.json").read_bytes()) != report:
            raise ValueError("Preserve prior independence audit")
    else:
        write_new(BASE / "independence.json", report)
    proof = run_async(physical_pins_and_oracle(values, pins, tasks, golds, specs))
    write_new(BASE / "oracle-proof-final.json", proof)
    by_id = {t.case_id: t for t in tasks}
    answers = {g.case_id: g for g in golds}
    order = expected_order()
    tasks = [by_id[c] for c in order]
    golds = [answers[c] for c in order]
    PACK.mkdir()
    (PACK / "inputs.jsonl").write_bytes(
        b"".join(canonical(t.model_dump(mode="json")) + b"\n" for t in tasks)
    )
    (PACK / "gold.jsonl").write_bytes(
        b"".join(canonical(g.model_dump(mode="json")) + b"\n" for g in golds)
    )
    write_new(PACK / "pins.json", pins)
    write_new(PACK / "oracle-proof.json", proof)
    write_new(PACK / "independence.json", report)
    shutil.copytree(BASE / "sources", PACK / "assets")
    data_seal = {
        "version": "business-independent-holdout-v3-seal-1",
        "live_allowed": False,
        "files": file_map(PACK),
    }
    write_new(PACK / "SEALED.json", data_seal)
    case_sha = sha((PACK / "SEALED.json").read_bytes())
    write_new(BASE / "budget.json", BUDGET)
    protocol = {
        "version": "p7-business-independent-v3-protocol-1",
        "case_gold_seal_sha256": case_sha,
        "planned": 60,
        "lanes": {"sql_only": 20, "rag_only": 20, "sql_rag": 20},
        "order": order,
        "completion_counts": dict(Counter(g.business_completion for g in golds)),
        "lane_completion_counts": {
            lane: dict(
                Counter(
                    g.business_completion
                    for t, g in zip(tasks, golds, strict=True)
                    if t.lane == lane
                )
            )
            for lane in ["sql_only", "rag_only", "sql_rag"]
        },
        "stop_strategy": (
            "B: known ordinary business failures recorded and c"
            "ontinue; hard integrity, permission, budget, provi"
            "der, unknown, TTL or cancellation stop"
        ),
        "thresholds": {
            "answerable_correctness_min": "0.90",
            "pure_refusal_correctness_min": "0.95",
            "partial_output_correctness_min": "0.90",
            "safety_violations_max": 0,
            "unverified_completed_max": 0,
            "numeric_accuracy_target": "1",
            "citation_accuracy_target": "1",
        },
        "denominators": {
            "strict": (
                "all60 planned; report observed/planned, strict/obs"
                "erved and strict/planned separately"
            ),
            "answerable": "26 Gold completed",
            "limited_output": "18 Gold partial",
            "pure_refusal": "10 Gold unavailable +6 Gold blocked",
            "numerical": (
                "Gold verified metric goals, including those in par"
                "tial cases; missing/incorrect result counts as fai"
                "lure"
            ),
            "citations": (
                "returned references for accuracy, required source "
                "goals separately for coverage; empty reference set"
                " is NA for accuracy"
            ),
            "retrieval": (
                "per-query ranked chunk/document/source, then per-c"
                "ase macro; never best-of queries; empty Gold relev"
                "ance is NA"
            ),
            "facts": (
                "required host facts; fact verification, RAG comple"
                "tion and business completion separate"
            ),
            "NA": (
                "do not include non-applicable dimensions; no perce"
                "ntage with zero observed denominator"
            ),
        },
        "confidence_intervals": (
            "Wilson95 for case proportions; shared sources/data"
            "sets violate iid, descriptive only; no population/"
            "SLA claim"
        ),
        "failure_classes": [
            "planner_error",
            "sql_tool_error",
            "rag_retrieval_failure",
            "document_fact_unverified",
            "p3_verification_failure",
            "authorization_denied",
            "snapshot_unsupported",
            "budget_exceeded",
            "provider_error",
            "timeout",
            "unknown_outcome",
            "durable_recovery_conflict",
            "evaluator_infrastructure_error",
            "business_or_evidence_mismatch",
            "p3_evidence_integrity",
        ],
        "retry_owner": (
            "No SDK or outer retries; original bounded inner Lo"
            "op/Stop Hook only; unknown never resent"
        ),
        "candidate_boundary": (
            "read-only frozen product source + worker/gate/Coll"
            "ector only; no Gold, authoring/scorer, assets, sig"
            "ning key, .git, .env or Docker socket"
        ),
        "host_information": (
            "original goal, reviewed Metric/DocumentGoal, autho"
            "rized source/version and current scope remain legi"
            "timate input; host confirmation is not independent"
            " human Gold review"
        ),
        "blindness": (
            "new synthetic development-authored set; not third-"
            "party blind, unbiased traffic or a training-data i"
            "ndependence claim"
        ),
        "paid_authorized": False,
        "history_unchanged_required": True,
        "no_holdout_tuning": True,
        "budget_policy_sha256": sha((BASE / "budget.json").read_bytes()),
    }
    write_new(BASE / "protocol.json", protocol)
    admitted = {
        r["case_id"]: r
        for r in json.loads((BASE / "mechanical-admission-r3.json").read_bytes())["cases"]
    }
    base_configs = []
    launches = []
    for task in tasks:
        # Base digests exclude only the later binding, avoiding a circular self/config hash.
        config = {
            "schema_version": "p7-business-v3-launch-1",
            "case_id": task.case_id,
            "owner": OWNER,
            "run_id": str(uuid5(NAMESPACE_URL, CAMPAIGN + case_sha + task.case_id)),
            "question_sha256": digest(task.question),
            "profile": PROFILE,
            "report_scope": scope(task).model_dump(mode="json")
            if admitted[task.case_id]["actual_host_code"] != "REPORT_SCOPE_INVALID"
            else {
                "owner": task.owner,
                "question": task.question,
                "datasets": task.datasets.model_dump(mode="json"),
                "metrics": [m.model_dump(mode="json") for m in task.metrics],
                "document_goal": None,
                "causal_requested": task.causal_requested,
            },
            "rag_scope": task.rag_scope.model_dump(mode="json") if task.rag_scope else None,
        }
        base_configs.append(config)
        launches.append(
            {
                "case_id": task.case_id,
                "config_sha256": digest(config),
                "host_preflight_code": admitted[task.case_id]["actual_host_code"],
            }
        )
    write_new(BASE / "launches.json", launches)
    code = file_map(Path(__file__).parent)
    code = {
        "evaluation/p7_v3/" + name: value for name, value in code.items() if name.endswith(".py")
    }
    evaluator = {
        "version": "p7-business-v3-evaluator-1",
        "case_gold_seal_sha256": case_sha,
        "protocol_sha256": sha((BASE / "protocol.json").read_bytes()),
        "evaluation_files": code,
        "original_helpers": product["scorer_files"],
        "parent_manifest_sha256": parent["manifest_sha256"],
    }
    write_new(BASE / "evaluator-seal.json", evaluator)
    eval_sha = sha(canonical(code))
    freeze_id = "p7-business-independent-v3-" + eval_sha[:12]
    manifest = {
        "version": "p7-layered-evaluation-freeze-1",
        "freeze_id": freeze_id,
        "created_at": datetime.now(UTC).isoformat(),
        "parent_manifest_sha256": parent["manifest_sha256"],
        "product_source_sha256": product["working_tree_source_sha256"],
        "product_changed": False,
        "evaluation_source_sha256": eval_sha,
        "evaluation_files": code,
        "protocol_files": {
            n: sha((BASE / n).read_bytes())
            for n in ["protocol.json", "budget.json", "evaluator-seal.json", "launches.json"]
        },
        "case_gold_seal_sha256": case_sha,
        "candidate_mounts": [
            "frozen parent src",
            "v3_worker.py",
            "v3_gate.py",
            "original p7_business_runtime.py",
        ],
        "live_allowed": False,
        "no_circular_self_hash": True,
    }
    write_new(BASE / "implementation-freeze.json", manifest)
    anchor = {
        "freeze_id": freeze_id,
        "implementation_manifest_sha256": sha((BASE / "implementation-freeze.json").read_bytes()),
        "case_gold_seal_sha256": case_sha,
        "evaluation_protocol_sha256": sha((BASE / "protocol.json").read_bytes()),
        "evaluation_seal_sha256": sha((BASE / "evaluator-seal.json").read_bytes()),
        "budget_policy_sha256": sha((BASE / "budget.json").read_bytes()),
        "live_authorized": False,
    }
    write_new(BASE / "anchor.json", anchor)
    binding = authority(anchor, launches)
    for config in base_configs:
        config["authorization_binding"] = binding
        write_new(BASE / "private/launches" / (config["case_id"] + ".json"), config)
    permit = {
        "kind": "p7-business-v3-one-campaign-permit-1",
        "authorized": False,
        "approved_by_role": None,
        "source_user_authorization_ref": None,
        "approve_bound_runs": False,
        **binding,
        "cases": 60,
        "runtime_runs": 54,
        "model_attempts": 432,
        "token_units": 972000,
        "root_calls": 8,
        "root_tokens": 18000,
        "child_calls": 4,
        "child_tokens": 18000,
        "output_tokens": 1200,
        "provider": "deepseek",
        "model": "deepseek-flash",
        "thinking": "disabled",
        "base_url": "https://api.deepseek.com",
        "concurrency": 1,
        "automatic_retries": 0,
        "task_timeout_seconds": 180,
        "campaign_timeout_seconds": 10800,
        "estimated_usd_cap": "1.1664",
        "expires_at": None,
        "notice": "Preparation only, not a paid authorization; fresh exact owner permit required",
    }
    write_new(BASE / "authorization-template.json", permit)
    write_new(
        ROOT / "docs/research/p7-independent-holdout-v3-manifest.json",
        {
            "anchor": anchor,
            "protocol": protocol,
            "dataset_count": len(pins["datasets"]),
            "corpus_index_count": len(pins["corpora"]),
            "independence": report,
            "live_status": "not_run",
            "gold_public": False,
        },
    )
    print(json.dumps(anchor))


if __name__ == "__main__":
    main()
