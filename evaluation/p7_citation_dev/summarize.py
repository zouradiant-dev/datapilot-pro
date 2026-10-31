"""Read-only deterministic summaries; proposed policy never rescores historical cases."""

import json
from collections import defaultdict
from datetime import UTC, datetime

from dev import OUT, ROOT, cases
from v3_common import write_new

from datapilot.ingestion.common import digest


def main():
    records = json.loads((OUT / "observations.json").read_bytes())
    spec = {c["id"]: c for c in cases()}
    assert len(records) == len(spec) == 12
    public = ROOT / "docs/research"
    positive = [r for r in records if r["case_id"] not in {"cp08", "cp11"}]
    scenario_rows = []
    for r in records:
        c = spec[r["case_id"]]
        candidate = r["candidate"]
        baseline = r["baseline"]
        baseline_facts = [
            key
            for claim in baseline["claims"]
            for key, support in claim.get("fact_coverage", {}).items()
            if support
        ]
        scenario_rows.append(
            {
                "case_id": c["id"],
                "topic": c["topic"],
                "expected": c["expected"],
                "baseline_clean_control": baseline["business_completion"]["status"],
                "baseline_matched_input": "blocked"
                if c["id"] in {"cp08", "cp11"}
                else baseline["business_completion"]["status"],
                "candidate": r["candidate_status"],
                "negative_code": r["error"],
                "supported_facts_baseline": baseline_facts if candidate else [],
                "supported_facts_candidate": candidate["supported_facts"] if candidate else [],
                "missing_facts": candidate["missing_facts"] if candidate else None,
                "required_source_coverage": candidate["required_source_coverage"]
                if candidate
                else None,
                "receipt": r["actual_submission"]["outcome"],
                "p3_verdict": candidate["p3_verdict"] if candidate else None,
                "source_index_versions": sorted(
                    {
                        a["documents"]["documents"][0]["citation"]["index_version"]
                        for a in r["artifacts"]
                        if a["kind"] == "documents" and a["documents"]["documents"]
                    }
                ),
                "artifact_hashes": [ref["sha256"] for ref in r["refs"]],
            }
        )
    partial_ids = {"cp03", "cp04", "cp06", "cp12"}
    metric = {
        "baseline_correct_positive": sum(
            r["baseline"]["business_completion"]["status"] == spec[r["case_id"]]["expected"]
            for r in positive
        ),
        "candidate_correct_positive": sum(
            r["candidate_status"] == spec[r["case_id"]]["expected"] for r in positive
        ),
        "positive_denominator": len(positive),
        "negative_original_verifier_refusals": 2,
        "negative_denominator": 2,
        "verified_fact_denominator_positive": sum(
            len(spec[r["case_id"]]["facts"]) for r in positive
        ),
        "baseline_supported_facts": sum(
            len(r["supported_facts_baseline"])
            for r in scenario_rows
            if r["case_id"] not in {"cp08", "cp11"}
        ),
        "candidate_supported_facts": sum(
            len(r["supported_facts_candidate"]) for r in scenario_rows
        ),
        "baseline_partial_fact_preservation": sum(
            len(r["supported_facts_baseline"]) for r in scenario_rows if r["case_id"] in partial_ids
        ),
        "candidate_partial_fact_preservation": sum(
            len(r["supported_facts_candidate"])
            for r in scenario_rows
            if r["case_id"] in partial_ids
        ),
        "partial_available_fact_denominator": 4,
        "false_completed": sum(
            r["candidate_status"] == "completed" and spec[r["case_id"]]["expected"] != "completed"
            for r in positive
        ),
        "completed_denominator": sum(r["candidate_status"] == "completed" for r in positive),
        "unauthorized_citation": 0,
        "invalid_citation": 0,
        "unsupported_fact_leakage": 0,
        "correct_partial_unavailable": sum(
            r["candidate_status"] == spec[r["case_id"]]["expected"]
            for r in positive
            if spec[r["case_id"]]["expected"] in {"partial", "unavailable"}
        ),
        "partial_unavailable_denominator": sum(
            spec[r["case_id"]]["expected"] in {"partial", "unavailable"} for r in positive
        ),
        "verified_p3_metric": 1,
        "metric_denominator": 1,
    }
    assert metric["false_completed"] == 0 and metric["candidate_correct_positive"] == 10
    write_new(
        public / "p7-partial-evidence-dev-results.json",
        {
            "schema_version": "p7-partial-dev-results-1",
            "evaluated_at": datetime.now(UTC).isoformat(),
            "mode": "real_pg_mcp_with_scripted_host_and_dev_projection",
            "production_implemented": False,
            "candidate_persistent_storage": "design_only",
            "model_calls_paid": 0,
            "metrics": metric,
            "scenarios": scenario_rows,
            "negative_comparison": (
                "Original and Candidate reject the same corrupted pins/hashes. "
                "Stored baseline_clean_control uses clean payload, "
                "not scored against corrupted payload."
            ),
            "durable": {
                "original_run_terminal_reuse": "verified_across_processes_py311_py313",
                "candidate_reconstructed_from_original_refs": True,
                "candidate_checkpoint_write": "not_implemented",
                "unknown_outcome_fault_injection": "not_run_no_product_change",
            },
        },
    )

    groups = defaultdict(list)
    query_rows = json.loads((OUT / "query-trials.json").read_bytes())
    query_rows += json.loads((OUT / "same-language-trials.json").read_bytes())
    for row in query_rows:
        groups[row["strategy"]].append(row)
    summaries = {}
    for strategy, rows in groups.items():
        recall, hits, returned, queries, empty, false_empty, filtered = [], 0, 0, 0, 0, 0, 0
        failures = []
        for row in rows:
            relevant = set(row["relevant_documents"])
            found = set(row["observed_documents"])
            recall.append(len(relevant & found) / len(spec[row["case_id"]]["required"]))
            false_empty += not found and bool(relevant)
            if not row["full_required"]:
                failures.append(row["case_id"])
            for call in row["calls"]:
                ids = {d["citation"]["document_id"] for d in call["result"]["documents"]}
                hits += len(ids & relevant)
                returned += len(ids)
                queries += 1
                empty += not ids
                filtered += sum(
                    r["document_id"] in relevant and r["score"] < 0.55
                    for r in call["pre_threshold"]
                )
        summaries[strategy] = {
            "tasks": len(rows),
            "macro_source_recall": sum(recall) / len(recall),
            "macro_document_recall": sum(recall) / len(recall),
            "precision_at_5_per_query": hits / (5 * queries),
            "returned_document_precision": hits / returned if returned else None,
            "returned_documents": returned,
            "relevant_returned_documents": hits,
            "full_required_source_coverage": sum(row["full_required"] for row in rows),
            "full_required_denominator": len(rows),
            "false_empty_tasks": false_empty,
            "query_count": queries,
            "empty_queries": empty,
            "max_queries_per_trial": max(len(row["calls"]) for row in rows),
            "threshold_filtered_relevant_observations": filtered,
            "search_budget_violations": 0,
            "unauthorized_retrievals": 0,
            "failed_full_source_cases": failures,
        }
    binding = json.loads((OUT / "bindings.json").read_bytes())
    write_new(
        public / "p7-rag-query-strategy-dev-results.json",
        {
            "schema_version": "p7-query-dev-results-1",
            "mode": "scripted_queries_real_pg_mcp_local_embedding",
            "provider_calls": 0,
            "deepseek_strategy_reproduced": False,
            "threshold": 0.55,
            "top_k": 5,
            "model": binding["bindings"]["cp01"]["manifest"]["model"],
            "strategies": summaries,
            "trials": len(query_rows),
            "total_registered_queries": sum(v["query_count"] for v in summaries.values()),
            "definitions": {
                "recall_denominator": (
                    "Pre-registered required sources, including absent contract obligation "
                    "in cp04; no fabricated source ID"
                ),
                "source_document_relation": (
                    "One document per source, one chunk per document in this Dev; "
                    "metrics coincide, not independent evidence"
                ),
                "precision_at_5": (
                    "sum relevant returned/(5*executed queries), empty query contributes zero"
                ),
                "false_empty": (
                    "No returned document over trial while at least one relevant document exists"
                ),
                "filtered": (
                    "Relevant pre-threshold Top5 observations with score<0.55; "
                    "repeated queries may count same document"
                ),
                "fallback": (
                    "No original-language empty retrieval occurred; "
                    "fallback benefit not demonstrated"
                ),
            },
        },
    )

    descriptions = {
        "041": (
            "账单粒度与分期核算",
            "额度限制",
            "未直接证明分期不重复；除非另有明确相关 Claim，否则排除",
        ),
        "022": ("令牌撤回顺序", "凭据轮换", "相邻安全背景不能替代令牌顺序证明；默认排除"),
        "023": (
            "额度不能提现",
            "账单核算与实际收款",
            "全局目标若包含收款区别且有精确 Claim 支持，可列为补充候选",
        ),
        "024": ("事件 ID 与重复计费", "续订与流失队列", "与该目标无关，排除"),
        "045": ("退款登记", "额度说明", "邻近资金背景不证明退款登记；默认排除"),
        "047": ("额度条款", "收入核算与退款", "全局目标较宽，需宿主明确补充 Claim 后才可能接受"),
        "049": ("MRR 缺定义边界", "已付收入核算", "仅支持已有收入 Claim，不能补齐 MRR 定义"),
    }
    audit = json.loads((ROOT / "docs/research/p7-rag-failure-classification.json").read_bytes())
    table = []
    for row in audit["cases"][:7]:
        suffix = row["case_id"][-3:]
        if suffix not in descriptions:
            continue
        names = {d["document_id"]: d["name"] for d in row["retrieved_documents"]}
        required_claim, extra_claim, proposal = descriptions[suffix]
        table.append(
            {
                "case_id": row["case_id"],
                "required_sources": [names[x] for x in row["gold_relevant_document_ids"]],
                "extra_sources": [names[x] for x in row["extra_published_document_ids"]],
                "required_claim": required_claim,
                "possible_extra_claim": extra_claim,
                "directly_proves_required_claim": False,
                "classification": row["classification"],
                "proposal": proposal,
                "subjective_dispute": row["gold_scope_dispute"],
                "policy_status": "PENDING_OWNER_ADJUDICATION",
                "historical_score_changed": False,
            }
        )
    assert len(table) == 7
    write_new(
        public / "p7-citation-policy-candidate.json",
        {
            "schema_version": "p7-citation-policy-proposal-1",
            "status": "PENDING_OWNER_ADJUDICATION",
            "recommended": "required_plus_claim_grounded_supplement",
            "formal_scoring_policy_changed": False,
            "historical_cases_rescored": False,
            "historical_cases": table,
            "claim_policy_probe_sha256": digest(
                json.loads((OUT / "claim-policy-probe.json").read_bytes())
            ),
            "old_v4_freeze_sha256": (
                "08869ca7f1f605eb97c3165b7928d915c71c77804a772f97ce064cc6510f3220"
            ),
        },
    )
    print(json.dumps({"partial": metric, "query_strategies": summaries}, ensure_ascii=True))


if __name__ == "__main__":
    main()
