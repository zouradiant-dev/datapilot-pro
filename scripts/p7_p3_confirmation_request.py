"""Prepare an exact read-only approval request. Never calls confirm_* or changes reviewed."""

import json
from collections import defaultdict

from p7_business_v2 import BASE, load_v2
from p7_gate2b import ROOT, write_new
from p7_holdout_pack import canonical, sha


def group_definitions(inputs, pins, pending_case_ids):
    for dataset in pins["datasets"].values():
        for kind in ("semantic", "metric"):
            seen = {}
            for pin in dataset[kind + "_definitions"]:
                version = (
                    pin["semantic_version"]
                    if kind == "semantic"
                    else (pin["metric_id"], pin["metric_version"])
                )
                if version in seen and seen[version] != pin["sha256"]:
                    raise ValueError("Same registry version has conflicting hashes")
                seen[version] = pin["sha256"]
    grouped = {}
    for task in inputs:
        if task["case_id"] not in pending_case_ids:
            continue
        for request in task["metrics"]:
            dataset = next(
                p
                for p in pins["datasets"].values()
                if (p["dataset_id"], p["dataset_version"])
                == (request["dataset_id"], request["dataset_version"])
            )
            alias = next(k for k, p in pins["datasets"].items() if p is dataset)
            definitions = [
                (
                    "semantic",
                    next(
                        p
                        for p in dataset["semantic_definitions"]
                        if p["semantic_version"] == request["semantic_version"]
                    ),
                ),
                (
                    "metric",
                    next(
                        p
                        for p in dataset["metric_definitions"]
                        if (p["metric_id"], p["metric_version"])
                        == (request["metric_id"], request["metric_version"])
                    ),
                ),
            ]
            for kind, pin in definitions:
                identity = {
                    "dataset_id": request["dataset_id"],
                    "dataset_version": request["dataset_version"],
                    "semantic_version": request["semantic_version"],
                    "kind": kind,
                    "definition_sha256": pin["sha256"],
                }
                if kind == "metric":
                    identity.update(
                        metric_id=request["metric_id"], metric_version=request["metric_version"]
                    )
                key = sha(canonical(identity))
                missing_unit = any(
                    e["entity"] == "invoices" and e["amount_storage"] is None
                    for e in next(
                        p
                        for p in dataset["semantic_definitions"]
                        if p["semantic_version"] == request["semantic_version"]
                    )["definition"]["entities"]
                )
                # Only a revenue metric uses the missing invoice-unit role. Other entities
                # containing nullable amount_storage are not incomplete money definitions.
                intentionally_unconfirmed = missing_unit and (
                    kind == "semantic" or request["metric_id"] == "paid_invoice_revenue"
                )
                category = (
                    "C_intentionally_unconfirmed_do_not_register"
                    if intentionally_unconfirmed
                    else "B_explicit_negative_test_policy"
                    if alias in {"late_history", "duplicate_meter"}
                    or (
                        kind == "metric"
                        and (
                            pin["definition"]["currency"] != "CNY"
                            or pin["definition"]["metric_id"] == "mrr"
                        )
                    )
                    else "A_complete_definition_pending_owner_confirmation"
                )
                if key not in grouped:
                    grouped[key] = {
                        "entry_id": key,
                        "identity": identity,
                        "dataset_alias": alias,
                        "source_sha256": dataset["source_sha256"],
                        "category": category,
                        "definition": pin["definition"],
                        "affected_case_ids": [],
                        "current_registry_state": "not_confirmed",
                        "approval_status": "pending",
                        "register_allowed_by_this_request": False,
                    }
                entry = grouped[key]
                if (
                    entry["definition"] != pin["definition"]
                    or sha(canonical(pin["definition"])) != pin["sha256"]
                ):
                    raise ValueError("Exact identity/hash definition conflict")
                if task["case_id"] not in entry["affected_case_ids"]:
                    entry["affected_case_ids"].append(task["case_id"])
    # A version identity cannot legitimately have two distinct content hashes.
    seen = {}
    for entry in grouped.values():
        ident = entry["identity"]
        key = canonical({k: v for k, v in ident.items() if k != "definition_sha256"})
        if key in seen and seen[key] != ident["definition_sha256"]:
            raise ValueError("Same version has conflicting hashes")
        seen[key] = ident["definition_sha256"]
    return sorted(
        grouped.values(),
        key=lambda e: (
            e["category"],
            e["dataset_alias"],
            e["identity"]["kind"],
            e["identity"].get("metric_id", ""),
            e["identity"].get("metric_version", 0),
            e["identity"]["semantic_version"],
        ),
    )


def main():
    tasks, pins, anchor = load_v2()
    admission = json.loads((BASE / "admission.json").read_bytes())
    pending = {c["case_id"] for c in admission["cases"] if c["p3_confirmation_missing"]}
    entries = group_definitions([t.model_dump(mode="json") for t in tasks], pins, pending)
    groups = defaultdict(list)
    for e in entries:
        groups[e["category"]].append(e["entry_id"])
    request = {
        "schema_version": "p3-owner-confirmation-request-1",
        "pack_sha256": anchor["seal_sha256"],
        "pending_tasks": len(pending),
        "entries": entries,
        "groups": dict(groups),
        "approval": None,
        "registry_writes_performed": 0,
        "scope": "exact original Registry definition requests; not Gold approval or data grants",
        "negative_policy_meaning": {
            "late_history": "review explicit history_complete=false; never assert complete history",
            "duplicate_meter": (
                "review expected event-ID grain; never assert duplicate data are unique"
            ),
            "USD": (
                "review a deliberately unsupported policy; no FX conversion or numeric publication"
            ),
            "mrr": "review a no-recipe test definition; do not invent recurring contract terms",
        },
        "excluded_missing_versions": [
            "bh2-019 metric version 999999",
            "bh2-048 dataset version 999999",
        ],
        "intentional_missing": (
            "C entries must remain unregistered; document text cannot approve amount unit"
        ),
        "apply_mechanism": (
            "After explicit approval of exact A/B entry IDs and this file SHA, "
            "use original Registry confirm_semantics/confirm_metric in version order; "
            "C never passed reviewed=True"
        ),
    }
    private = BASE / "private/p3-confirmation-request.json"
    write_new(private, request)
    digest = sha(private.read_bytes())
    counts = {k: len(v) for k, v in groups.items()}
    summary = {
        "schema_version": request["schema_version"],
        "manifest_sha256": digest,
        "private_manifest": private.relative_to(ROOT).as_posix(),
        "pack_sha256": anchor["seal_sha256"],
        "pending_task_count": len(pending),
        "unique_entries": len(entries),
        "semantic_entries": sum(e["identity"]["kind"] == "semantic" for e in entries),
        "metric_entries": sum(e["identity"]["kind"] == "metric" for e in entries),
        "category_counts": counts,
        "approval": None,
        "registry_writes": 0,
    }
    write_new(ROOT / "docs/research/p7-p3-confirmation-summary.json", summary)
    lines = [
        "# P3 精确批量确认请求（尚未批准）",
        "",
        f"清单字节 SHA256：`{digest}`。",
        "",
        "A：完整定义，待明确批准。B：完整的负例政策，只确认所列限制，不批准计算能力或修复坏数据。",
        "C：故意未确认的金额单位及依赖定义，排除在批量批准和 Registry 登记之外。",
        "",
        "本文件不代填 reviewed=True，不登记业务定义。批准 Gold 流程的旧消息不是本清单的批准。",
        "",
        "|分组|Dataset|种类|Semantic|Metric / 版本|定义 SHA|涉及 Case|",
        "|---|---|---|---|---|---|---|",
    ]
    for e in entries:
        i = e["identity"]
        lines.append(
            f"|{e['category'][0]}|{e['dataset_alias']} / {i['dataset_id']} v{i['dataset_version']}|"
            f"{i['kind']}|{i['semantic_version']}|{i.get('metric_id', '—')} / "
            f"{i.get('metric_version', '—')}|"
            f"{i['definition_sha256']}|{', '.join(e['affected_case_ids'])}|"
        )
    lines += [
        "",
        "完整字段映射、单位、UTC 日期覆盖、历史完整性、paid/churn/feature 政策如下；"
        "审批精确绑定 JSON 字节 SHA。",
        "",
        "```json",
        json.dumps(request, ensure_ascii=False, indent=2),
        "```",
        "",
        "可用批准格式：批准上述 SHA 对应清单中的 A/B 明确 entry_id，"
        "接受其中不完整/不支持条件保持原值；C 不登记。",
    ]
    (BASE / "private/p3-confirmation-request.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))


def write_context_policies():
    """A missing-definition negative remains missing; no Registry confirmation occurs."""
    request = json.loads((BASE / "private/p3-confirmation-request.json").read_bytes())
    tasks, _, _ = load_v2()
    launches = json.loads((BASE / "launches.json").read_bytes())
    excluded = [e for e in request["entries"] if e["category"].startswith("C_")]
    index = {}
    for launch in launches["cases"]:
        if launch["stage"] != "runtime":
            continue
        task = next(t for t in tasks if t.case_id == launch["case_id"])
        path = ROOT / launch["path"]
        config = json.loads((path / "config.json").read_bytes())
        missing = {}
        for goal in task.metrics:
            matching = [
                e
                for e in excluded
                if task.case_id in e["affected_case_ids"]
                and e["identity"]["dataset_id"] == goal.dataset_id
                and e["identity"]["dataset_version"] == goal.dataset_version
                and e["identity"]["semantic_version"] == goal.semantic_version
            ]
            if matching:
                if {e["identity"]["kind"] for e in matching} != {"semantic", "metric"}:
                    raise ValueError("Incomplete negative prerequisite classification")
                missing[goal.goal_id] = {
                    "expected_hashes": config["expected_contexts"][goal.goal_id],
                    "required_error_code": "SEMANTIC_NOT_CONFIRMED",
                }
        policy = {
            "case_id": task.case_id,
            "config_sha256": sha((path / "config.json").read_bytes()),
            "required_missing": missing,
            "registry_writes": 0,
            "authority_expansion": False,
        }
        write_new(path / "context-policy.json", policy)
        index[task.case_id] = {
            "path": (path / "context-policy.json").relative_to(ROOT).as_posix(),
            "sha256": sha((path / "context-policy.json").read_bytes()),
            "required_missing_goals": list(missing),
        }
    write_new(BASE / "context-policy-index.json", index)
    print(
        json.dumps(
            {
                "policies": len(index),
                "intentional_missing_cases": sum(
                    bool(p["required_missing_goals"]) for p in index.values()
                ),
                "registry_writes": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
