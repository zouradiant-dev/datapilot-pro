"""Local contracts and redaction, explicitly no model or database."""

import ast
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from datapilot.contracts import AgentFailure
from datapilot.web.config import HostPolicy
from datapilot.web.contracts import CreateTask, TaskAction
from datapilot.web.service import safe_name
from datapilot.web.telemetry import Observation, export_local


@pytest.mark.parametrize(
    "name",
    [
        "../a.csv",
        "a/b.xlsx",
        "x.exe",
        "CON.csv",
        "LPT1.csv",
        "x.csv; DROP TABLE users",
        ".hidden.csv",
        "a.csv ",
    ],
)
def test_names_are_not_paths(name):
    with pytest.raises(AgentFailure):
        safe_name(name, {".csv", ".xlsx"})


def test_public_requests_cannot_choose_owner_permissions_or_sql():
    with pytest.raises(ValidationError):
        TaskAction(confirmed=True, owner="other")
    with pytest.raises(ValidationError):
        CreateTask(question="x", metrics=[], sql="DELETE FROM x")


def test_private_object_cannot_escape(tmp_path):
    policy = HostPolicy(secret="test", data_dir=tmp_path)
    with pytest.raises(ValueError):
        policy.object_path("../secret.txt")
    assert policy.object_path(str(uuid4()) + "/中文.csv").is_relative_to(tmp_path)


def test_telemetry_allowlist_and_failure(tmp_path):
    with pytest.raises(ValidationError):
        Observation(run_id="r", prompt="secret", sql="SELECT secret")
    with pytest.raises(ValidationError):
        Observation(run_id="r", endpoint_alias="https://secret@host")
    record = Observation(run_id="r", input_tokens=10, latency_ms=1)
    assert export_local([record], tmp_path / "trace.jsonl")
    assert "input_tokens" in (tmp_path / "trace.jsonl").read_text()
    assert not export_local([record], tmp_path / "missing" / "trace")


def test_ui_imports_only_http_client():
    # Enforced once the real UI exists; no source-text matching masquerading as E2E.
    path = Path(__file__).parents[1] / "src/datapilot/web/ui.py"
    assert path.exists()
    modules = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
        if isinstance(node, ast.Import):
            modules.extend(a.name for a in node.names)
    assert not any(
        m.startswith(
            (
                "datapilot.persistence",
                "datapilot.semantics",
                "datapilot.runtime",
                "sqlalchemy",
                "langgraph",
            )
        )
        for m in modules
    )
