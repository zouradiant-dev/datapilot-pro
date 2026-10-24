"""Explicit P7 intent evaluation; never launches or approves a business Run."""

import argparse
import hashlib
import json
import time
from datetime import date
from pathlib import Path

from datapilot.evaluation import IntentGold, IntentObservation, intent_summary, signature
from datapilot.web.chat_contracts import ChatSelection
from datapilot.web.intent import resolve

ROOT = Path(__file__).resolve().parents[1]


def read_cases(split):
    manifest = json.loads(
        (ROOT / "docs/research/p7-intent-corpus-manifest.json").read_text(encoding="utf-8")
    )
    selected = manifest["splits"][split]
    path = ROOT / selected["path"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != selected["sha256"]:
        raise ValueError("Corpus hash changed")
    if split == "holdout":
        # Both code and experimental model configuration must be frozen before opening Gold.
        freeze = ROOT / "artifacts/p7/candidate-freeze.json"
        if not freeze.exists():
            raise ValueError("Holdout remains sealed until candidate code/configuration freeze")
        frozen = json.loads(freeze.read_text(encoding="utf-8"))
        if not frozen.get("holdout_authorized", False):
            raise ValueError("Gate 2 has not been authorized; Holdout remains sealed")
        for name, sha in frozen["files"].items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha:
                raise ValueError("Frozen candidate source changed; do not tune against Holdout")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def rule_baseline(cases):
    observations = []
    for case in cases:
        started = time.perf_counter()
        draft = resolve(
            case["question"],
            ChatSelection.model_validate_json(json.dumps(case["selection"])),
            case["datasets"],
            today=date.fromisoformat(case["today"]),
            previous=case["previous"],
        )
        observations.append(
            IntentObservation(
                case_id=case["case_id"],
                strategy="rule_only",
                transport="none",
                expected=IntentGold.model_validate_json(json.dumps(case["expected"])),
                actual=signature(draft),
                elapsed_ms=(time.perf_counter() - started) * 1000,
                reported_tokens=0,
                provider_cache_read_tokens=0,
            )
        )
    return observations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "holdout"], default="dev")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    path = args.output.resolve()
    if not path.is_relative_to((ROOT / "artifacts/p7").resolve()):
        parser.error("Write private task-level results only inside artifacts/p7")
    observations = rule_baseline(read_cases(args.split))
    result = {
        "schema_version": "p7-intent-results-1",
        "split": args.split,
        "observations": [o.model_dump(mode="json") for o in observations],
        "summary": intent_summary(observations),
        "agent_e2e": "not_run",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps(result["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
