"""New public facts through real PG/MCP/Worker/Report/Durable; decisions are scripted."""

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from reporting_fixtures import host_scope
from test_partial_evidence_postgres import snapshot
from test_qwen_migration_postgres import ingest_public

from datapilot.contracts import AgentFailure
from datapilot.orchestration.runtime import text_hash
from datapilot.persistence.inspection import inspect_run
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.contracts import RagScope, Target
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService, make_pin
from datapilot.reporting.contracts import CitationPolicy, CitationSource, confirm_finite_scope

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "tests/fixtures/rag/host-goal-requirements-v2.json").read_bytes())["e2e"]
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", params=["bge", "qwen"])
def fresh_ownership(request, portable_pg, tmp_path_factory):
    if request.param == "qwen" and os.getenv("DATAPILOT_RUN_QWEN_TESTS") != "1":
        pytest.skip("Explicit real CUDA Qwen test opt-in required")
    folder = tmp_path_factory.mktemp("ownership-" + request.param)
    sources = {
        k: v
        for k, v in DATA["sources"].items()
        if k != ("ownership-en.md" if request.param == "bge" else "ownership-zh.md")
    }
    if request.param == "qwen":
        scope, manifest = ingest_public(
            portable_pg, folder / "assets", sources, "qwen3-cuda-fp16-v1"
        )
    else:
        assets = folder / "assets"
        assets.mkdir()
        for name, text in sources.items():
            (assets / name).write_text(text, encoding="utf-8")
        scope = RagScope(allow_saas=True)
        service = IngestionService(
            os.environ["DATAPILOT_RAG_INGEST_DATABASE_URL"], LocalEmbedding()
        )
        try:
            manifest, index, _, _ = service.ingest(
                Target(corpus_id=str(uuid4())),
                sorted(assets.glob("*.md")),
                scope=scope,
                reviewed=True,
            )
        finally:
            service.close()
        scope.corpora = [make_pin(manifest, index)]
    binding = {
        "scope": scope.model_dump(mode="json"),
        "manifest": manifest.model_dump(mode="json"),
        "metric": None,
    }
    (folder / "binding.json").write_text(json.dumps(binding), encoding="utf-8")
    with pytest.MonkeyPatch.context() as patch:
        # A subprocess must re-create exactly the current trusted host policy, not .env defaults.
        for key, value in portable_pg.model_dump().items():
            if isinstance(value, (str, bool, int, float)):
                patch.setenv("DATAPILOT_" + key.upper(), str(value))
        yield portable_pg, folder, request.param, sources, binding


def configured(dev, kind):
    _, _, arm, sources, binding = dev
    name = "ownership-en.md" if arm == "qwen" else "ownership-zh.md"
    quote = DATA["fact_quote_en" if arm == "qwen" else "fact_quote_zh"]
    question = DATA["causal_query"] if kind == "causal" else DATA["query"]
    if kind == "exhaustive":
        question = DATA["exhaustive_query"]
    if kind == "unrelated_required":
        name = "billing.md"
    facts = [["approval", name, quote]]
    if kind == "partial":
        facts.append(["missing_retention", None, None])
    if kind == "missing":
        facts = [["missing_retention", None, None]]
    if kind == "unrelated_required":
        # Requiring this source does not confirm an approval rule absent from it.
        facts = [["approval", None, None]]
    case = {
        "id": "public-host-goal-" + kind,
        "question": question,
        "documents": sources,
        "facts": facts,
    }
    rag, report = host_scope(case, binding)
    source = next(s for s in binding["manifest"]["sources"] if s["name"] == name)
    report.partial_evidence_policy = "partial-facts-v1"
    report.rag_query_policy = "original-first-v1"
    report.causal_requested = kind == "causal"
    report.citation_policy = CitationPolicy(
        goal_sha256=text_hash(question),
        required_sources=[
            CitationSource(
                corpus_id=rag.corpora[0].corpus_id,
                index_version=rag.corpora[0].index_version,
                source_id=source["source_id"],
                document_id=source["document_id"],
                version=source["version"],
                source_sha256=source["text_sha256"],
            )
        ],
    )
    return rag, report


def probe(dev, action, run_id, rag, report, *args, expected=0):
    _, folder, _, _, _ = dev
    path = folder / (run_id + ".json")
    if not path.exists():
        path.write_text(
            json.dumps(
                {
                    "rag_scope": rag.model_dump(mode="json"),
                    "report_scope": report.model_dump(mode="json"),
                }
            ),
            encoding="utf-8",
        )
    result = subprocess.run(
        [sys.executable, str(ROOT / "tests/host_goal_probe.py"), action, run_id, str(path), *args],
        cwd=ROOT,
        env={**os.environ, "PYTHONUTF8": "1"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=150,
    )
    log = folder / (run_id + "-" + action + "-" + uuid4().hex + ".log")
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == expected, f"See retained probe log: {log}"
    if expected == 91 and not result.stdout:
        return {"process_exit": 91}
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "kind", ["complete", "partial", "missing", "exhaustive", "causal", "unrelated_required"]
)
def test_new_public_ownership_report_chain(fresh_ownership, kind):
    settings, folder, _, _, _ = fresh_ownership
    rag, report = configured(fresh_ownership, kind)
    if kind in {"complete", "partial", "causal"}:
        report = confirm_finite_scope(
            report, rag, confirmation_ref="public-ci-final31-ownership-review"
        )
    id_ = str(uuid4())
    result = probe(fresh_ownership, "start", id_, rag, report)
    expected = DATA["expected"][kind]
    assert result["business_completion"]["status"] == expected
    assert result["cross_source_report"]["charts"] == []
    assert all(c["metric"] is None for c in result["cross_source_report"]["claims"])
    if kind == "causal":
        assert (
            "causal_conclusion_not_verified" in result["business_completion"]["unconfirmed_claims"]
        )
    if kind == "complete":
        task = result["results"]["1:documents"]
        assert task["rag_completion"]["verdict"] == "semantic_retrieval"
        assert task["rag_completion"]["relevant_chunk_ids"]
        assert task["rag_completion"]["business_conclusions_verified"] is False
    verified = run_async(
        inspect_run(
            settings, id_, report.owner, report.question, report_scope=report, rag_scope=rag
        )
    )
    assert not verified["unknown"] and verified["report"]
    (folder / (id_ + "-inspection.json")).write_text(
        json.dumps({"run_id": id_, "kind": kind, "status": expected, "usage": verified["usage"]}),
        encoding="utf-8",
    )


@pytest.mark.parametrize("fault", ["owner", "version"])
def test_host_goal_text_never_grants_scope_or_version(fresh_ownership, fault):
    settings, _, _, _, _ = fresh_ownership
    rag, report = configured(fresh_ownership, "complete")
    bad = rag.model_copy(deep=True)
    if fault == "owner":
        bad.owner = "other-owner"
    else:
        bad.corpora[0].index_version = "0" * 64
    with pytest.raises(AgentFailure):
        run_async(
            run_durable(settings, str(uuid4()), report.question, rag_scope=bad, report_scope=report)
        )


def test_new_goal_cross_process_restore_preserves_receipt_and_budget(fresh_ownership):
    settings, _, _, _, _ = fresh_ownership
    rag, report = configured(fresh_ownership, "complete")
    report = confirm_finite_scope(
        report, rag, confirmation_ref="public-ci-final31-ownership-restore-review"
    )
    id_ = str(uuid4())
    first = probe(fresh_ownership, "start", id_, rag, report, "--pause")
    assert first["status"] == "paused"
    resumed = probe(fresh_ownership, "resume", id_, rag, report)
    before = snapshot(settings, id_, report.owner)
    repeated = probe(fresh_ownership, "resume", id_, rag, report)
    assert resumed["business_completion"]["status"] == "completed"
    assert resumed["cross_source_report"] == repeated["cross_source_report"]
    assert resumed["usage"] == repeated["usage"]
    assert before == snapshot(settings, id_, report.owner)


def test_legacy_requirement_manifest_is_not_silently_reinterpreted(fresh_ownership):
    settings, _, _, _, _ = fresh_ownership
    rag, report = configured(fresh_ownership, "complete")
    report = confirm_finite_scope(
        report, rag, confirmation_ref="public-ci-legacy-recovery-scope-review"
    )
    id_ = str(uuid4())
    first = probe(fresh_ownership, "start", id_, rag, report, "--pause", "--legacy")
    assert first["status"] == "paused"
    before = snapshot(settings, id_, report.owner)
    denied = probe(fresh_ownership, "resume", id_, rag, report, expected=2)
    assert denied["error"]["code"] == "RECOVERY_IDENTITY"
    assert before == snapshot(settings, id_, report.owner)
