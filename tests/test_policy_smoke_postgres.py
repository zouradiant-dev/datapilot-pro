"""Portable PG/MCP pack preflight; no Docker launcher, paid model or old Holdout."""

import importlib
import os
from pathlib import Path

import pytest

from datapilot.persistence.session import run_async


@pytest.mark.integration
def test_public_policy_pack_exact_pins_and_host_denial(
    reporting_dev, portable_pg, tmp_path_factory, monkeypatch
):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    prepare = importlib.import_module("p7_policy_smoke_prepare")
    runner = importlib.import_module("p7_policy_smoke_run")
    dev, settings = reporting_dev
    output = tmp_path_factory.mktemp("three-policy-pack-parent") / "pack"
    if requested := os.getenv("DATAPILOT_POLICY_PREP_DIR"):
        output = Path(requested).resolve()
        assert output.is_relative_to(root / "artifacts/p7")
    cases, pins = prepare.assemble(dev, settings, os.environ, output)
    assert len(cases) == 8 and sum(c.preflight_denial is None for c in cases) == 7
    assert [c.case_id for c in cases] == [f"tps-{i:02}" for i in range(1, 9)]
    for case in cases:
        if case.document_goal:
            assert case.scope.partial_evidence_policy == "partial-facts-v1"
            assert case.scope.rag_query_policy == "original-first-v1"
            assert case.scope.citation_policy.schema_version == "required-supplement-v1"
        code = run_async(runner.preflight(case, portable_pg, pins))
        assert code == case.preflight_denial
    assert prepare.oracle(output / "assets/invoices.csv") == "637.45"
