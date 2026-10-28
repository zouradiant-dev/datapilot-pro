"""CI failure preservation and isolated profile; never contacts GitHub or a provider."""

from pathlib import Path

import pytest
import yaml
from reporting_fixtures import validate_environment


@pytest.fixture
def workflow():
    path = Path(__file__).parents[1] / ".github/workflows/test.yml"
    # BaseLoader preserves 'on' and boolean spellings under YAML 1.1 parsers.
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_both_matrix_versions_finish_without_fail_fast(workflow):
    job = workflow["jobs"]["checks"]
    assert job["strategy"]["matrix"]["python"] == ["3.11", "3.13"]
    assert job["strategy"]["fail-fast"] == "false"
    assert workflow["on"] == ["push", "pull_request"]


def test_ci_roles_use_same_disposable_database_and_no_model_key(workflow):
    job = workflow["jobs"]["checks"]
    assert validate_environment(job["env"]).llm_mode == "fake"
    assert job["env"]["DATAPILOT_API_KEY"] == ""
    assert job["env"]["DATAPILOT_RUN_LIVE_TESTS"] == "0"
    assert job["env"]["DATAPILOT_P7_ISOLATED"] == "1"
    service = job["services"]["postgres"]
    assert service["env"]["POSTGRES_DB"] == "datapilot_test_ci"
    assert ":0.8.6-pg17@sha256:" in service["image"]


def test_failure_is_not_masked_by_tee_or_continue_on_error(workflow):
    for step in workflow["jobs"]["checks"]["steps"]:
        assert "continue-on-error" not in step
        if "run" in step:
            assert step["shell"] == "bash"
            assert "set -euo pipefail" in step["run"]
            assert "|| true" not in step["run"]


def test_failed_unit_step_does_not_hide_pg_or_static_evidence(workflow):
    steps = workflow["jobs"]["checks"]["steps"]
    pg = next(s for s in steps if "integration.xml" in s.get("run", ""))
    assert "!cancelled()" in pg["if"] and "steps.initialize.outcome" in pg["if"]
    assert "-m integration" in pg["run"] and "--cov-append" in pg["run"]
    unit = next(s for s in steps if "unit.xml" in s.get("run", ""))
    assert "not integration and not live" in unit["run"]
    assert any("--collect-only" in s.get("run", "") for s in steps)
    for step in steps:
        if "ruff " in step.get("run", ""):
            assert "!cancelled()" in step["if"]


def test_upload_preserves_each_attempt_without_private_test_artifacts(workflow):
    upload = workflow["jobs"]["checks"]["steps"][-1]
    assert upload["if"] == "${{ always() }}"
    assert upload["uses"].startswith("actions/upload-artifact@")
    options = upload["with"]
    assert options["path"] == "artifacts/ci/"
    assert options["include-hidden-files"] == "false"
    assert options["if-no-files-found"] == "error"
    assert "matrix.python" in options["name"] and "github.run_attempt" in options["name"]
    assert options.get("overwrite", "false") == "false"
