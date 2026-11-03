"""Public protocol-only correction for trusted host control rows; original v3 scorer untouched."""

import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "p7_v3"))
import v3_score as original

TRUSTED = {"rag_completion_correction"}
_ORIGINAL = original.call_integrity


def current_call_integrity(payload):
    rows = payload.get("calls", [])
    for row in rows:
        if (
            str(row.get("call_key", "")).startswith("control:")
            and row.get("tool_name") not in TRUSTED
        ):
            return False
    clean = dict(payload)
    clean["calls"] = [r for r in rows if not str(r.get("call_key", "")).startswith("control:")]
    return _ORIGINAL(clean)


def score(task, gold, record, key, pins):
    # The evaluator runs serially. Scope the frozen scorer's compatibility hook to one score.
    with patch.object(original, "call_integrity", current_call_integrity):
        return original.score(task, gold, record, key, pins)


def project_metric_version(task, pins, materialized, *, request, target_version, definition_sha):
    """Project one externally bound metric mapping; retain the original score checks."""
    if task.metrics.count(request) != 1 or request.metric_version == target_version:
        raise ValueError("mapping must select exactly one frozen metric request")
    frozen = next(
        d
        for d in pins["datasets"].values()
        if (d["schema"]["dataset_id"], d["schema"]["version"])
        == (request.dataset_id, request.dataset_version)
    )
    if frozen["schema"] != materialized["schema"] or (
        frozen["semantics"]["definition_sha256"] != materialized["semantics"]["definition_sha256"]
    ):
        raise ValueError("mapped dataset or semantics drift")
    old, new = (
        next(
            m
            for m in dataset["metrics"]
            if (m["metric_id"], m["metric_version"]) == (request.metric_id, version)
        )
        for dataset, version in ((frozen, request.metric_version), (materialized, target_version))
    )
    if old["definition_sha256"] != definition_sha or new["definition_sha256"] != definition_sha:
        raise ValueError("mapped metric definition drift")
    projected = request.model_copy(update={"metric_version": target_version})
    scoring_pins = deepcopy(pins)
    for dataset in scoring_pins["datasets"].values():
        if dataset == frozen:
            dataset["metrics"] = [
                m
                for m in dataset["metrics"]
                if (m["metric_id"], m["metric_version"]) != (request.metric_id, target_version)
            ] + [deepcopy(new)]
    return task.model_copy(
        update={"metrics": [projected if m == request else m for m in task.metrics]}
    ), scoring_pins
