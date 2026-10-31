"""Versioned offline diagnosis: reuse v3 business scoring, replace protocol validation only."""

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluation/p7_v3"))

import v3_score as original  # noqa: E402
from v3_common import BASE, canonical, load, read_answers, sha, verify  # noqa: E402
from v4_protocol import Digest, Strict, inspect_protocol  # noqa: E402


class EvaluatorFreeze(Strict):
    schema_version: Literal["p7-scorer-v4-freeze-1"]
    evaluator_id: str = Field(pattern=r"^p7-scorer-v4-[a-f0-9]{12}$")
    mode: Literal["offline_diagnostic_only"]
    live_allowed: Literal[False]
    created_at: str
    parent_implementation_sha256: Digest
    parent_evaluator_sha256: Digest
    original_result_seal_sha256: Digest
    code_sha256: Digest
    code_files: dict[str, Digest]
    observed_collection_sha256: dict[str, Digest]
    witness_manifest_sha256: Digest
    witness_manifest_path: Literal["artifacts/p7/scorer-v4/private/witness-manifest-r2.json"]


def verify_evaluator(path):
    parent, _, _ = verify()
    raw = Path(path).read_bytes()
    frozen = EvaluatorFreeze.model_validate_json(raw)
    current = {
        p.relative_to(ROOT).as_posix(): sha(p.read_bytes())
        for p in Path(__file__).parent.glob("*.py")
    }
    if (
        frozen.parent_implementation_sha256 != parent["implementation_manifest_sha256"]
        or frozen.parent_evaluator_sha256 != parent["evaluation_seal_sha256"]
        or current != frozen.code_files
        or sha(canonical(current)) != frozen.code_sha256
        or frozen.evaluator_id != "p7-scorer-v4-" + frozen.code_sha256[:12]
    ):
        raise ValueError("V4 evaluator identity or code differs; no v3 Seal substitution")
    result_seal = BASE / "private/live-audit-v1/RESULT-SEAL-v1.json"
    if sha(result_seal.read_bytes()) != frozen.original_result_seal_sha256:
        raise ValueError("Original result seal differs")
    return frozen


def bound_witness(frozen, case_id, path, key):
    manifest_path = ROOT / frozen.witness_manifest_path
    raw = manifest_path.read_bytes()
    if sha(raw) != frozen.witness_manifest_sha256:
        raise ValueError("Journal witness manifest differs from the evaluator Seal")
    manifest = json.loads(raw)
    if manifest["signing_key_sha256"] != sha(key) or manifest["files"].get(case_id) != sha(
        path.read_bytes()
    ):
        raise ValueError("Witness file/key is not the sealed trusted audit source")
    return json.loads(path.read_bytes())


def score(task, gold, record, collector_key, pins, witness, witness_key):
    result = original.score(task, gold, record, collector_key, pins)
    audit = inspect_protocol(record, collector_key, witness, witness_key)
    result = dict(result)
    result["evaluator"] = "v4_offline_diagnostic"
    result["original_v3_strict_correct"] = result["strict_correct"]
    result["protocol_audit"] = audit
    if "dimensions" in result:
        result["dimensions"] = result["dimensions"] | {"protocol": audit["valid"]}
        result["strict_correct"] = all(v is not False for v in result["dimensions"].values())
        if result["strict_correct"]:
            result["failure_class"] = None
        elif not audit["valid"]:
            result["failure_class"] = "tool_protocol_provenance_invalid"
    elif not audit["valid"]:
        result["strict_correct"] = False
        result["failure_class"] = "tool_protocol_provenance_invalid"
    return result


def main():
    parser = argparse.ArgumentParser(description="Read existing signed records only; no Runtime")
    for name in ["record", "collector-key", "witness", "witness-key", "freeze"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    frozen = verify_evaluator(args.freeze)
    record = json.loads(args.record.read_bytes())
    case_id = record["payload"]["case_id"]
    if frozen.observed_collection_sha256.get(case_id) != sha(args.record.read_bytes()):
        raise ValueError("Not one of the authorized existing observations; no new case run")
    tasks, pins, _ = load()
    task = next(t for t in tasks if t.case_id == case_id)
    witness_key = args.witness_key.read_bytes()
    witness = bound_witness(frozen, case_id, args.witness, witness_key)
    result = score(
        task,
        read_answers()[case_id],
        record,
        args.collector_key.read_bytes(),
        pins,
        witness,
        witness_key,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
