"""Fresh registration; original ingestion/metric/binding helpers remain unmodified."""

import json
import os
import re
import secrets
import sys
from collections import Counter
from datetime import UTC, datetime
from difflib import SequenceMatcher

from datapilot.config import Settings
from datapilot.ingestion.common import digest

from .common import ARMS, HERE, OUT, ROOT, cases, manifest, module, order, sha, write_new


def environment():
    v = json.loads((OUT / "environment-private.json").read_bytes())
    assert v["DATAPILOT_ADMIN_DATABASE_URL"].endswith(
        "/datapilot_test_fresh_validation_v3r2_20261030"
    )
    os.environ.update(v)
    os.environ.update(DATAPILOT_API_KEY="", DATAPILOT_LLM_MODE="fake", DATAPILOT_RUN_LIVE_TESTS="0")
    return v, Settings(
        _env_file=None,
        llm_mode="fake",
        api_key=None,
        model="fresh-scripted-v3",
        max_model_calls=8,
        max_total_tokens=18000,
        max_worker_turns=4,
    )


impl = module("prepare")
impl.environment = environment


def normalized(s, numeric=False):
    s = re.sub(r"[\W_]+", "", s.casefold())
    return re.sub(r"\d+", "#", s) if numeric else s


def independence(rows):
    inputs = [
        "evaluation/qwen_business_pilot/cases.json",
        "evaluation/qwen_expanded_quality/cases.json",
        "tests/fixtures/rag/embedding-ab-dev.json",
        "tests/fixtures/rag/qwen-migration-dev.json",
        "tests/fixtures/rag/qwen-migration-safety.json",
        "evaluation/p7_citation_dev/cases.json",
        "tests/fixtures/rag/host-goal-requirements-v2.json",
        "tests/fixtures/rag/host-goal-requirements-v3.json",
        "tests/fixtures/rag/language-boundary.json",
        "tests/fixtures/rag/reporting-cases.json",
    ]
    old_queries = []
    old_documents = []
    sources = []

    def visit(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in {
                    "query",
                    "question",
                    "doc_query",
                    "causal_query",
                    "exhaustive_query",
                } and isinstance(v, str):
                    old_queries.append(v)
                elif k in {"documents", "sources"} and isinstance(v, dict):
                    old_documents.extend(t for t in v.values() if isinstance(t, str))
                else:
                    visit(v)
        elif isinstance(x, list):
            for v in x:
                visit(v)

    for name in inputs:
        visit(json.loads((ROOT / name).read_bytes()))
        sources.append({"path": name, "sha256": sha(ROOT / name)})
    newq = [c.query for c in rows]
    newdoc = [t for c in rows for t in c.documents.values()]
    for numeric in [False, True]:
        assert len(set(normalized(q, numeric) for q in newq)) == 100
        assert not set(normalized(q, numeric) for q in newq) & set(
            normalized(q, numeric) for q in old_queries
        )
    assert not set(newdoc) & set(old_documents)
    assert len(set(newdoc)) == len(newdoc), (
        "Shared document bodies require explicit control disclosure"
    )
    near = []
    for c in rows:
        matches = sorted(
            (
                (SequenceMatcher(None, normalized(c.query), normalized(q)).ratio(), q)
                for q in set(old_queries)
            ),
            reverse=True,
        )
        near.append(
            {
                "case": c.id,
                "old_query": matches[0][1],
                "lexical_ratio": matches[0][0],
                "relationship": c.relationship,
                "fact_pattern": c.fact_pattern,
                "expected_status": c.expected_status,
            }
        )
    return {
        "public_sources": sources,
        "exact_query_duplicates": 0,
        "normalized_or_numeric_query_duplicates": 0,
        "exact_old_document_overlap": 0,
        "new_document_count": len(newdoc),
        "new_shared_document_bodies": 0,
        "nearest_public_query_by_case": near,
        "structure_dependencies": dict(
            Counter((c.relationship + ":" + c.fact_pattern) for c in rows)
        ),
        "numeric_recipe_dependency": (
            "Ten new invoice snapshots and varied service claims, one reviewed "
            "paid-invoice recipe; not ten independent arithmetic algorithms"
        ),
        "review": (
            "AI-assisted business scenario/claim/source-relation review; no "
            "independent human blind review"
        ),
        "not_proved": (
            "Zero lexical/hash overlap cannot prove semantic independence; same "
            "author, recurring SaaS concepts and common reporting contracts "
            "remain dependencies"
        ),
        "sealed_gold_read": False,
    }


def register():
    rows = cases()
    review = independence(rows)
    write_new(OUT / "independence-review.json", review)
    expected = {}
    for c in rows:
        folder = OUT / "sources" / c.id
        folder.mkdir(parents=True, exist_ok=False)
        for name, text in c.documents.items():
            (folder / name).write_bytes(text.encode("utf-8"))
        if c.metric:
            (folder / "invoices.csv").write_bytes(c.metric_input["csv"].encode("utf-8"))
        expected[c.id] = {}
        for arm in ARMS:
            m = manifest(c, arm)
            for _, name, quote in c.facts + c.supplementary:
                if name:
                    s = next(s for s in m.sources if s.name == name)
                    assert any(quote in c.documents[name][p.start : p.end] for p in s.chunks), (
                        c.id,
                        name,
                        "quote crosses chunk",
                    )
            expected[c.id][arm] = {
                "manifest": m.model_dump(mode="json"),
                "index_version": digest(m),
            }
        assert (
            expected[c.id]["bge"]["manifest"]["sources"]
            == expected[c.id]["qwen"]["manifest"]["sources"]
        )
    parent = ROOT / "artifacts/p7/host-goal-safety-v3/implementation-delivery.json"
    files = dict(json.loads(parent.read_bytes())["files"])
    for name, h in files.items():
        assert sha(ROOT / name) == h, name
    extra = list(HERE.glob("*.py")) + [
        HERE / "cases-r2.json",
        ROOT / "tests/test_qwen_fresh_validation.py",
    ]
    extra += list((ROOT / "evaluation/qwen_expanded_quality").glob("*.py"))
    extra += list((OUT / "sources").glob("*/*"))
    files.update({p.relative_to(ROOT).as_posix(): sha(p) for p in extra})
    seq = [c.id for c in order("dev")] + [c.id for c in order("validation")]
    reg = {
        "schema_version": "fresh-business-validation-registration-1",
        "registered_at": datetime.now(UTC).isoformat(),
        "parent_implementation_sha256": sha(parent),
        "cases_sha256": sha(HERE / "cases-r2.json"),
        "files": files,
        "expected_indexes": expected,
        "batches": [seq[i : i + 20] for i in range(0, 100, 20)],
        "planned_cases": 100,
        "planned_arm_observations": 200,
        "dev": 20,
        "validation": 80,
        "expected_runtime_per_arm": sum(not c.preflight for c in rows),
        "arm_order": "odd ordinal BGE/Qwen; even ordinal Qwen/BGE, serial",
        "requirement_policy": "host-goal-requirements-v3",
        "gold_author": (
            "AI-assisted explicit synthetic facts and independent Decimal/SQL; "
            "not Agent-derived or human blind review"
        ),
        "scoring": {
            "strict": (
                "Exact state, fact set, independent P3 Decimal/unit, original "
                "reference verifier and causal guard, plus exact Gold goal "
                "class/unsupported"
            ),
            "source": (
                "First actual Top-3 chunks deduplicated by Source; not three unique "
                "sources or best-of-search"
            ),
            "gate_a": (
                "Zero false business or unsupported retrieval completion, unsupported "
                "facts/citations/numbers/causality/scope, unknown resend, "
                "identity/evaluation integrity errors"
            ),
            "gate_b": (
                "Complete Validation: Required/Fact macro coverage strictly higher, "
                "micro precision not lower, unrelated/stale counts not increased"
            ),
            "gate_c": (
                "Complete Validation: positive paired strict difference; CI and exact "
                "McNemar reported separately, not production assurance"
            ),
            "stop": (
                "First hard "
                "safety/freeze/scope/unknown/budget/infrastructure/integrity error "
                "stops next arm and batches; ordinary quality failures continue; no "
                "reruns"
            ),
            "uncertainty": (
                "Complete cohorts only; seed20261030 category-stratified paired "
                "bootstrap10000 + exact McNemar; stopped subset descriptive only"
            ),
        },
        "limits": {
            "root_calls": 8,
            "child_calls": 4,
            "tokens": 18000,
            "worker_turns": 4,
            "max_searches": 2,
            "script_searches": 1,
            "top_k": 3,
            "mcp_seconds": 10,
            "paid_calls": 0,
        },
        "independence_sha256": sha(OUT / "independence-review.json"),
        "compatibility_stamp": (
            "registration-r2.json is a byte-identical copy for the unchanged "
            "prior driver, not a second/newly amended Gold version"
        ),
    }
    write_new(OUT / "registration.json", reg)
    (OUT / "registration-r2.json").write_bytes((OUT / "registration.json").read_bytes())
    with (OUT / "collector-key-private.bin").open("xb") as f:
        f.write(secrets.token_bytes(32))
    print("Frozen 100 new cases, 20/80, 200 expected indexes; no retrieval or Runtime executed")


if __name__ == "__main__":
    if sys.argv[1:] == ["register"]:
        register()
    else:
        impl.main()
