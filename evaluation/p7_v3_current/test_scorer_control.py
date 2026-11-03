import sys
from pathlib import Path

sys.path.insert(0, str(Path("evaluation/p7_v3_current").resolve()))
import scorer

sys.path.insert(0, str(Path("evaluation/p7_v4").resolve()))
from test_v4_contracts import fixture


def test_public_trusted_control_row_is_accepted():
    payload, _ = fixture()
    assert scorer.original.call_integrity(payload) is False
    assert scorer.current_call_integrity(payload) is True


def test_metric_mapping_preserves_request_and_rejects_drift():
    from copy import deepcopy
    from datetime import date

    import pytest

    from datapilot.contracts import Contract
    from datapilot.semantics.contracts import MetricRequest

    class Task(Contract):
        metrics: list[MetricRequest]

    request = MetricRequest(
        goal_id="metric_1",
        dataset_id="75135051-a537-54a4-b834-f88786512bf4",
        dataset_version=2,
        semantic_version=1,
        metric_id="active_subscriptions",
        metric_version=3,
        as_of=date(2026, 1, 1),
    )
    task = Task(metrics=[request])
    old = {
        "schema": {"dataset_id": request.dataset_id, "version": 2, "source_sha256": "a" * 64},
        "semantics": {"definition_sha256": "b" * 64},
        "metrics": [
            {"metric_id": request.metric_id, "metric_version": 3, "definition_sha256": "c" * 64}
        ],
    }
    new = deepcopy(old)
    new["metrics"][0]["metric_version"] = 1
    pins = {"datasets": {"synthetic": old}}
    kwargs = dict(request=request, target_version=1, definition_sha="c" * 64)
    projected, mapped = scorer.project_metric_version(task, pins, new, **kwargs)
    assert projected.metrics == [request.model_copy(update={"metric_version": 1})]
    assert (
        task.metrics == [request]
        and pins["datasets"]["synthetic"]["metrics"][0]["metric_version"] == 3
    )
    assert mapped["datasets"]["synthetic"]["metrics"][-1] == new["metrics"][0]
    new["metrics"][0]["definition_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="metric definition drift"):
        scorer.project_metric_version(task, pins, new, **kwargs)
    new["schema"]["source_sha256"] = "e" * 64
    with pytest.raises(ValueError, match="dataset or semantics drift"):
        scorer.project_metric_version(task, pins, new, **kwargs)
