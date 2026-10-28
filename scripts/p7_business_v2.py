"""Versioned evaluation inputs only; original Runtime/Gold and authorization stay intact."""

import argparse
import copy
import json
import shutil

from p7_gate2b import ROOT, environment, inspect, pack, write_new
from p7_holdout_pack import CaseInput, canonical, sha, verify_seal

from datapilot.ingestion.common import digest
from datapilot.rag.contracts import IndexManifest

BASE = ROOT / "artifacts/p7/gate2b-v2"
DEST = BASE / "sealed-business-v2"
SUBSETS = {"bh2-030", "bh2-033", "bh2-035", "bh2-038", "bh2-040", "bh2-054", "bh2-059"}
BLOCKED_INPUTS = {"bh2-018", "bh2-019", "bh2-020", "bh2-034", "bh2-048", "bh2-058"}


def revise(inputs, pins):
    revised, catalog = copy.deepcopy(inputs), copy.deepcopy(pins)
    manifests = {p["index_version"]: (alias, p) for alias, p in pins["corpora"].items()}
    diffs = []
    for task in revised:
        if task["case_id"] not in SUBSETS:
            continue
        for pin in task["rag_scope"]["corpora"]:
            group, original = manifests[pin["index_version"]]
            old = original["manifest"]
            ids = set(pin["document_ids"])
            if not ids or not ids <= {s["document_id"] for s in old["sources"]}:
                raise ValueError("Subset must preserve exact original grants")
            manifest = copy.deepcopy(old)
            manifest["sources"] = [s for s in old["sources"] if s["document_id"] in ids]
            version = digest(manifest)
            IndexManifest.model_validate_json(json.dumps(manifest))
            alias = "subset-" + version[:16]
            catalog["corpora"][alias] = {
                "manifest": manifest,
                "index_version": version,
                "dataset_alias": original["dataset_alias"],
                "source_group": group,
                "status": "requires_materialization",
            }
            diffs.append(
                {
                    "case_id": task["case_id"],
                    "old_index": pin["index_version"],
                    "new_index": version,
                    "corpus_id": pin["corpus_id"],
                    "document_ids_unchanged": list(pin["document_ids"]),
                    "source_group": group,
                }
            )
            pin["index_version"] = version
    if {d["case_id"] for d in diffs} != SUBSETS:
        raise ValueError("All seven compatibility cases must be retained")
    for task in revised:
        CaseInput.model_validate_json(json.dumps(task))
    return revised, catalog, diffs


def build():
    parent, public = pack()
    owner = json.loads((ROOT / "docs/research/p7-owner-admission.json").read_bytes())
    if not owner["effective"] or not owner["engineering_v2_authorized"]:
        raise ValueError("Owner engineering decision missing")
    if DEST.exists():
        raise ValueError("Preserve existing v2 and failed stages; never overwrite")
    inputs = [json.loads(line) for line in (parent / "inputs.jsonl").read_bytes().splitlines()]
    revised, pins, diffs = revise(inputs, json.loads((parent / "pins.json").read_bytes()))
    DEST.mkdir(parents=True)
    shutil.copytree(parent / "assets", DEST / "assets")
    for name in ("gold.jsonl", "oracle-proof.json", "candidate-freeze.json", "evaluator-only.json"):
        shutil.copyfile(parent / name, DEST / name)
    (DEST / "inputs.jsonl").write_bytes(b"".join(canonical(t) + b"\n" for t in revised))
    (DEST / "pins.json").write_bytes(canonical(pins))
    rules = {
        "version": "business-admission-scoring-2",
        "denominator": 60,
        "owner_decision_sha256": sha((ROOT / "docs/research/p7-owner-admission.json").read_bytes()),
        "default": {"execution_phase": "runtime", "semantic_refusal_requires_adjudication": True},
        "cases": {
            **{
                id_: {"execution_phase": "preflight", "no_business_or_model_calls": True}
                for id_ in sorted(BLOCKED_INPUTS)
            },
            "bh2-001": {"execution_phase": "runtime", "customer_linkage_and_invoice_grain": True},
            "bh2-048": {
                "execution_phase": "preflight",
                "no_business_or_model_calls": True,
                "retrieval_facts_are_conditional_reference_only": True,
                "user_action": "confirm_dataset_version",
            },
            "bh2-055": {
                "execution_phase": "runtime",
                "chart_units_if_present": True,
                "chart_required": False,
            },
        },
    }
    write_new(DEST / "acceptance-rules.json", rules)
    mapping = [
        {
            "old_case_id": t["case_id"],
            "new_case_key": "business-v2/" + t["case_id"],
            "question_unchanged": t["question"] == original["question"],
            "numeric_gold_unchanged": True,
        }
        for t, original in zip(revised, inputs, strict=True)
    ]
    write_new(
        DEST / "revision.json",
        {
            "version": "business-v2",
            "parent_seal_sha256": public["seal_sha256"],
            "parent_pack": str(parent.relative_to(ROOT)),
            "input_changes": diffs,
            "acceptance_clarifications": ["bh2-001", "bh2-048", "bh2-055"],
            "case_mapping": mapping,
            "cases": 60,
            "lanes": {"sql_only": 20, "rag_only": 20, "sql_rag": 20},
            "gold_bytes_identical_to_parent": (DEST / "gold.jsonl").read_bytes()
            == (parent / "gold.jsonl").read_bytes(),
            "blindness": "known compatibility revision; not a fresh blind holdout",
            "p3_confirmation": "separate_required",
            "live_authorized": False,
        },
    )
    marker = {
        "version": "business-v2-seal-1",
        "live_allowed": False,
        "files": {
            p.relative_to(DEST).as_posix(): sha(p.read_bytes())
            for p in sorted(DEST.rglob("*"))
            if p.is_file()
        },
    }
    (DEST / "SEALED.json").write_bytes(canonical(marker))
    write_new(
        BASE / "v2-anchor.json",
        {
            "pack": DEST.relative_to(ROOT).as_posix(),
            "seal_sha256": sha((DEST / "SEALED.json").read_bytes()),
            "parent_seal_sha256": public["seal_sha256"],
        },
    )
    print(json.dumps({"cases": 60, "changed_inputs": len(diffs), "gold_unchanged": True}))


def load_v2():
    anchor = json.loads((BASE / "v2-anchor.json").read_bytes())
    verify_seal(DEST, expected_seal_sha256=anchor["seal_sha256"])
    # Hash validation is allowed; candidate execution never reads Gold.
    inputs = [
        CaseInput.model_validate_json(line)
        for line in (DEST / "inputs.jsonl").read_bytes().splitlines()
    ]
    return inputs, json.loads((DEST / "pins.json").read_bytes()), anchor


def materialize():
    from datapilot.rag.contracts import RagScope
    from datapilot.rag.models import LocalEmbedding
    from datapilot.rag.storage import IngestionService, make_pin

    inspect()
    _, pins, anchor = load_v2()
    service = IngestionService(environment()["DATAPILOT_RAG_INGEST_DATABASE_URL"], LocalEmbedding())
    receipt = []
    try:
        for alias, item in pins["corpora"].items():
            if not alias.startswith("subset-"):
                continue
            expected = IndexManifest.model_validate_json(json.dumps(item["manifest"]))
            target = expected.target
            scope = RagScope.model_validate_json(
                json.dumps(
                    {
                        "owner": target.owner,
                        "allow_saas": target.dataset_id is None,
                        "datasets": {
                            "bindings": [
                                {"dataset_id": target.dataset_id, "version": target.dataset_version}
                            ]
                            if target.dataset_id
                            else []
                        },
                        "corpora": [
                            make_pin(expected, item["index_version"]).model_dump(mode="json")
                        ],
                    }
                )
            )
            paths = [
                DEST / "assets/documents" / item["source_group"] / s.name for s in expected.sources
            ]
            actual, version, reused, usage = service.ingest(
                target, paths, scope=scope, reviewed=True, chunker=expected.chunker
            )
            if actual != expected or version != item["index_version"]:
                raise ValueError("Materialized subset differs from approved original closure")
            receipt.append(
                {
                    "index_version": version,
                    "corpus_id": target.corpus_id,
                    "sources": len(actual.sources),
                    "reused": reused,
                    "embedding_usage": usage.model_dump(mode="json") if usage else None,
                }
            )
    finally:
        service.close()
    write_new(
        BASE / "subset-materialization.json",
        {
            "seal": anchor["seal_sha256"],
            "indexes": receipt,
            "paid_calls": 0,
            "scope_expanded": False,
        },
    )
    print(json.dumps({"indexes": len(receipt), "scope_expanded": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["build", "materialize"])
    action = parser.parse_args().action
    {"build": build, "materialize": materialize}[action]()
