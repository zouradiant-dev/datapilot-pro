"""Real PG17/MCP/BGE, public Dev sources reused, only new Fake-scripted Runs."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from test_document_fact_postgres import host_fact
from test_partial_evidence_postgres import (
    assert_no_new_budget_usage,
    config_for,
    snapshot,
)
from test_partial_evidence_postgres import (
    dev_environment as dev_environment,
)

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import Artifact
from datapilot.orchestration.runtime import ArtifactStore, text_hash
from datapilot.persistence.session import run_async
from datapilot.rag.contracts import RagScope
from datapilot.rag.mcp import rag_session
from datapilot.reporting.contracts import CitationSource, ReportScope
from datapilot.reporting.service import report_session

ROOT = Path(__file__).resolve().parents[1]
OUT = None  # Bound by the module reporting_output fixture.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("reporting_output"),
    pytest.mark.skipif(
        os.getenv("DATAPILOT_RUN_DB_TESTS") != "1", reason="Explicit isolated PostgreSQL opt-in"
    ),
]


def configured(dev, case_id="cp09"):
    config = config_for(dev, case_id)
    binding = json.loads((dev.OUT / "bindings.json").read_bytes())["bindings"][case_id]
    primary = "quota.md" if case_id == "cp09" else "delivery.md"
    name, quote = (
        ("rounding.md", "展示值向上取整到整MiB")
        if case_id == "cp09"
        else ("delivery.md", "电子账单补寄采用邮件队列")
    )
    supplement = host_fact(binding, name, "supplement", quote)
    source = next(s for s in binding["manifest"]["sources"] if s["name"] == primary)
    pin = binding["scope"]["corpora"][0]
    config["report_scope"]["citation_policy"] = {
        "schema_version": "required-supplement-v1",
        "goal_sha256": text_hash(config["report_scope"]["question"]),
        "required_sources": [
            {
                "corpus_id": pin["corpus_id"],
                "index_version": pin["index_version"],
                "source_id": source["source_id"],
                "document_id": source["document_id"],
                "version": source["version"],
                "source_sha256": source["text_sha256"],
            }
        ],
        "supplementary_claims": [supplement.model_dump(mode="json")],
    }
    return config


def probe(config, action, run_id, *args, expected=0):
    folder = OUT / run_id
    folder.mkdir(exist_ok=True)
    path = folder / (digest(config) + ".json")
    if not path.exists():
        path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/citation_policy_probe.py"),
            action,
            run_id,
            str(path),
            *args,
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=110,
    )
    log = folder / (action + "-" + uuid4().hex + ".log")
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == expected, f"Probe failed; private log: {log}"
    return json.loads(result.stdout) if result.stdout.strip() else None


@pytest.mark.parametrize("case_id", ["cp09", "cp07"])
def test_real_policy_report_terminal_reuse_preserves_citations_p3_and_budget(
    dev_environment, case_id
):
    dev, settings = dev_environment
    config, run_id = configured(dev, case_id), str(uuid4())
    first = probe(config, "start", run_id, *(["--insufficient"] if case_id == "cp07" else []))
    assert first["business_completion"]["status"] == (
        "completed" if case_id == "cp09" else "partial"
    )
    context = next(c for c in first["cross_source_report"]["claims"] if c["kind"] == "context")
    assert context["supplementary_coverage"]["supplement"]["excerpt"]
    before = snapshot(settings, run_id, config["report_scope"]["owner"])
    repeated = probe(config, "resume", run_id)
    assert repeated["cross_source_report"] == first["cross_source_report"]
    assert repeated["usage"] == first["usage"]
    assert snapshot(settings, run_id, config["report_scope"]["owner"]) == before
    if case_id == "cp07":
        metric = next(
            c["metric"] for c in first["cross_source_report"]["claims"] if c["kind"] == "metric"
        )
        assert metric["verdict"] == metric["verification"]["verdict"] == "verified"
        assert "documents" not in first["business_completion"]["verified_goals"]


@pytest.mark.parametrize(
    "cut", ["rag_submission_committed", "report_artifact_committed", "checkpoint"]
)
def test_new_policy_survives_cross_process_cut_without_model_reissue(dev_environment, cut):
    dev, settings = dev_environment
    config, run_id = configured(dev), str(uuid4())
    if cut == "checkpoint":
        assert probe(config, "start", run_id, "--pause")["status"] == "paused"
    else:
        probe(config, "start", run_id, "--cut", cut, expected=91)
    before = snapshot(settings, run_id, config["report_scope"]["owner"])
    first = probe(config, "resume", run_id)
    assert first["business_completion"]["status"] == "completed"
    assert first["cross_source_report"]["claims"][0]["supplementary_coverage"]
    after = snapshot(settings, run_id, config["report_scope"]["owner"])
    assert_no_new_budget_usage(before["ledger"], after["ledger"])
    assert [c for c in before["calls"] if c["kind"] == "model"] == [
        c for c in after["calls"] if c["kind"] == "model"
    ]
    assert all(after["artifacts"][k] == v for k, v in before["artifacts"].items())


def test_legacy_policy_is_not_silently_upgraded_on_resume(dev_environment):
    dev, settings = dev_environment
    new, run_id = configured(dev), str(uuid4())
    legacy = json.loads(json.dumps(new))
    del legacy["report_scope"]["citation_policy"]
    first = probe(legacy, "start", run_id)
    before = snapshot(settings, run_id, legacy["report_scope"]["owner"])
    assert probe(new, "resume", run_id, expected=2)["error"]["code"] == "RECOVERY_IDENTITY"
    assert snapshot(settings, run_id, legacy["report_scope"]["owner"]) == before
    assert probe(legacy, "resume", run_id)["cross_source_report"] == first["cross_source_report"]


def test_real_supplement_only_and_forged_quotes_cannot_fill_required_sources(dev_environment):
    dev, settings = dev_environment
    config = configured(dev)
    scope = ReportScope.model_validate_json(json.dumps(config["report_scope"]))
    rag = RagScope.model_validate_json(json.dumps(config["rag_scope"]))

    async def check():
        async with (
            rag_session(settings, rag, goal=scope.question) as retrieval,
            report_session(settings, scope, scope.question, scope.owner) as service,
        ):
            result = await retrieval.search(scope.question, 5)
            store = ArtifactStore("new-citation-partial-pg")
            selected = result.model_copy(deep=True)
            selected.documents = [d for d in selected.documents if d.source == "rounding.md"]
            assert selected.documents
            ref = store.put(
                Artifact(
                    run_id=store.run_id,
                    task_id="documents",
                    plan_version=1,
                    kind="documents",
                    source="real-pg-scoped-test-subset",
                    documents=selected,
                )
            )
            pairs = [(ref, store.get(ref))]
            report = service.build(pairs, retrieval)
            assert report.business_completion.status == "unavailable"
            assert report.claims[0].supplementary_coverage
            assert (
                "required_document_source_missing"
                in report.business_completion.missing_evidence["documents"]
            )
            service.scope.citation_policy.supplementary_claims[0].quotation = "虚构收益翻倍"
            invalid = service.build(pairs, retrieval)
            assert not any(c.supplementary_coverage for c in invalid.claims)
            service.scope.citation_policy.required_sources[0].index_version = "0" * 64
            with pytest.raises(AgentFailure):
                service.build(pairs, retrieval)

    run_async(check())


def test_real_unrelated_source_is_not_published_even_after_separate_search(dev_environment):
    dev, settings = dev_environment
    case = next(c for c in dev.cases() if c["id"] == "cp10")
    binding = json.loads((dev.OUT / "bindings.json").read_bytes())["bindings"]["cp10"]
    rag, scope = dev.host_scope(case, binding)
    c = scope.document_goal.required_facts[0].citation
    raw = scope.model_dump(mode="json")
    raw["citation_policy"] = {
        "schema_version": "required-supplement-v1",
        "goal_sha256": text_hash(scope.question),
        "required_sources": [c.model_dump(include=set(CitationSource.model_fields))],
    }
    scope = ReportScope.model_validate_json(json.dumps(raw))

    async def check():
        async with (
            rag_session(settings, rag, goal=scope.question) as retrieval,
            report_session(settings, scope, scope.question, scope.owner) as service,
        ):
            store, pairs = ArtifactStore("new-citation-unrelated-pg"), []
            for query in [scope.question, "果园夏季滴灌和桃树修剪"]:
                result = await retrieval.search(query, 5)
                if query != scope.question:
                    assert any(d.source == "orchard.md" for d in result.documents)
                ref = store.put(
                    Artifact(
                        run_id=store.run_id,
                        task_id="documents",
                        plan_version=1,
                        kind="documents",
                        source="real-mcp-two-searches",
                        documents=result,
                    )
                )
                pairs.append((ref, store.get(ref)))
            report = service.build(pairs, retrieval)
            assert report.business_completion.status == "completed"
            assert all("果园" not in d.excerpt for c in report.claims for d in c.documents)
            assert not any(c.supplementary_coverage for c in report.claims)

    run_async(check())
