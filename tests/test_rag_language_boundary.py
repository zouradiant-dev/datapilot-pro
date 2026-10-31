"""Public language Dev. Protocol assertions do not assert away quality failures."""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.contracts import BudgetLimits, TaskEnvelope, TaskSpec
from datapilot.orchestration.rag_completion import retrieval_goal
from datapilot.orchestration.runtime import ArtifactStore
from datapilot.orchestration.tools import ToolRegistry
from datapilot.rag.contracts import RagScope, Target
from datapilot.rag.mcp import rag_session
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService, make_pin

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "tests/fixtures/rag/language-boundary.json"


@pytest.fixture(scope="module")
def probe_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "language_boundary_probe", ROOT / "scripts/language_boundary_probe.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_predeclared_plan_preserves_sources_and_language_matrix(probe_module):
    plan = probe_module.load_plan(PLAN)
    assert len(plan["cases"]) == 12
    assert {(c["query_language"], c["document_language"]) for c in plan["cases"]} == {
        ("zh", "zh"),
        ("zh", "en"),
        ("en", "zh"),
        ("en", "en"),
    }
    assert len(plan["sources"]["zh"]) == 6 and len(plan["sources"]["en"]) == 2
    assert plan["sources"]["en"]["keys.md"] == (PLAN.parent / "keys.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("change", ["threshold", "duplicate_id", "unknown_source"])
def test_plan_drift_is_rejected(probe_module, tmp_path, change):
    data = json.loads(PLAN.read_bytes())
    if change == "threshold":
        data["parameters"]["min_score"] = 0.54
    elif change == "duplicate_id":
        data["cases"][1]["id"] = data["cases"][0]["id"]
    else:
        data["cases"][0]["relevant_sources"] = ["unapproved.md"]
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        probe_module.load_plan(p)


def test_metrics_do_not_turn_empty_negatives_into_perfect_recall(probe_module):
    sources = [
        {"name": "a.md", "source_id": "s", "document_id": "d", "chunks": [{"chunk_id": "c"}]}
    ]
    positive = probe_module.measure([], sources, ["a.md"])
    negative = probe_module.measure([], sources, [])
    assert positive["recall_at_k"] == 0 and positive["wrong_empty"]
    assert negative["recall_at_k"] is None and negative["reciprocal_rank"] is None
    assert negative["negative_correct"] and negative["precision_at_k"] is None


def test_source_coverage_and_precision_use_independent_labels(probe_module):
    sources = [
        {
            "name": "a.md",
            "source_id": "a",
            "document_id": "da",
            "chunks": [{"chunk_id": "a1"}, {"chunk_id": "a2"}],
        },
        {"name": "b.md", "source_id": "b", "document_id": "db", "chunks": [{"chunk_id": "b1"}]},
    ]
    citations = [
        {"chunk_id": "b1", "source_id": "b", "document_id": "db"},
        {"chunk_id": "a1", "source_id": "a", "document_id": "da"},
    ]
    result = probe_module.measure(citations, sources, ["a.md"])
    assert result["recall_at_k"] == result["precision_at_k"] == result["reciprocal_rank"] == 0.5
    assert result["source_coverage"] == 1 and result["returned_sources"] == 2
    assert result["irrelevant_chunks"] == 1
    with pytest.raises(ValueError):
        probe_module.measure(citations * 2, sources, ["a.md"])
    citations[0]["source_id"] = "a"
    with pytest.raises(ValueError):
        probe_module.measure(citations, sources, ["a.md"])


@pytest.fixture(scope="module")
def language_data(portable_pg, tmp_path_factory, probe_module):
    plan = probe_module.load_plan(PLAN)
    output = tmp_path_factory.mktemp("language-boundary")
    requested = os.getenv("DATAPILOT_LANGUAGE_RESULTS_DIR")
    if requested:
        output = Path(requested).resolve()
        assert output.is_relative_to(ROOT / "artifacts")
        output.mkdir(parents=True, exist_ok=False)
    owner = "language-dev-" + uuid4().hex[:16]
    embedding = LocalEmbedding()
    bindings = {}
    ingestor = IngestionService(os.environ["DATAPILOT_RAG_INGEST_DATABASE_URL"], embedding)
    try:
        for lang, sources in plan["sources"].items():
            folder = output / lang
            folder.mkdir()
            paths = []
            for name, text in sources.items():
                path = folder / name
                path.write_bytes(text.encode("utf-8"))
                paths.append(path)
            scope = RagScope(owner=owner, allow_saas=True)
            manifest, version, _, _ = ingestor.ingest(
                Target(corpus_id=str(uuid4()), owner=owner), paths, scope=scope, reviewed=True
            )
            scope.corpora = [make_pin(manifest, version)]
            bindings[lang] = {
                "scope": scope.model_dump(mode="json"),
                "manifest": manifest.model_dump(mode="json"),
            }
    finally:
        ingestor.close()
    (output / "bindings.json").write_text(
        json.dumps(bindings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    yield plan, bindings, portable_pg, embedding, output


def test_summary_retains_wrong_empty_without_claiming_business_completion(probe_module):
    sources = [
        {"name": "a.md", "source_id": "s", "document_id": "d", "chunks": [{"chunk_id": "c"}]}
    ]
    rows = [
        {
            "id": "positive",
            "answerable": True,
            "language_pair": "en->en",
            "kind": "paired_language_matrix",
            "metrics": probe_module.measure([], sources, ["a.md"]),
        },
        {
            "id": "negative",
            "answerable": False,
            "language_pair": "en->en",
            "kind": "absent_source_negative",
            "metrics": probe_module.measure([], sources, []),
        },
    ]
    result = probe_module.summarize(rows)
    assert not result["overall"]["quality_gate_passed"]
    assert result["overall"]["wrong_empty"] == result["overall"]["negative_correct"] == 1
    assert result["worker_completion"] == result["business_completion"] == "not_run"
    with pytest.raises(ValueError):
        probe_module.summarize([])
    with pytest.raises(ValueError):
        probe_module.summarize(rows + rows)


@pytest.mark.integration
@pytest.mark.parametrize("case_id", [c["id"] for c in json.loads(PLAN.read_bytes())["cases"]])
async def test_language_retrieval_matches_scoped_pg_and_retains_quality_failures(
    probe_module, language_data, case_id
):
    plan, bindings, settings, embedding, output = language_data
    case = next(c for c in plan["cases"] if c["id"] == case_id)
    binding = bindings[case["document_language"]]
    scope = RagScope.model_validate_json(json.dumps(binding["scope"]))
    assert scope.min_score == 0.55
    manifest, ranked = probe_module.prefilter(
        settings.rag_reader_database_url.get_secret_value(), scope, case["query"], embedding
    )
    assert digest(manifest) == scope.corpora[0].index_version
    run = "language-dev-" + uuid4().hex
    envelope = TaskEnvelope(
        run_id=run,
        parent_id=run,
        plan_version=1,
        task=TaskSpec(task_id="documents", worker="rag", instruction=case["query"]),
        allowed_tools=["search_documents"],
        budget=BudgetLimits(),
    )
    store = ArtifactStore(run)
    goal = retrieval_goal(case["query"])
    async with rag_session(settings, scope, goal=case["query"]) as tools:
        registry = ToolRegistry(envelope, store, retrieval=tools, rag_goal=goal)
        await registry.invoke(
            "search_documents", {"query": case["query"], "top_k": 5}, call_id="first-search"
        )
        assert registry.search_attempts == 1 and tools.max_search_attempts == 2
        result = store.get(registry.refs[-1]).documents
        assert not result.fixture
        expected = [r["chunk_id"] for r in ranked[:5] if r["score"] >= 0.55]
        assert [d.citation.chunk_id for d in result.documents] == expected
        qualified = tools.qualifying_documents(result.documents, goal)
        citations = [d.citation.model_dump(mode="json") for d in result.documents]
    metrics = probe_module.measure(
        citations, binding["manifest"]["sources"], case["relevant_sources"]
    )
    record = {
        **case,
        "language_pair": case["query_language"] + "->" + case["document_language"],
        "scope_sha256": digest(scope),
        "manifest_sha256": digest(manifest),
        "ranked_before_threshold": ranked,
        "citations": citations,
        "goal_qualified_chunks": [d.citation.chunk_id for d in qualified],
        "metrics": metrics,
        "unavailable_reason": result.unavailable_reason,
        "search_attempts": registry.search_attempts,
        "embedding_usage": result.embedding_usage.model_dump(),
        "worker_completion": "not_run",
        "business_completion": "not_run",
    }
    # Keep negatives and misses; a quality failure is not an observer/protocol failure.
    (output / (case_id + ".json")).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@pytest.mark.integration
async def test_other_owner_cannot_read_language_dev_corpus(language_data):
    _, bindings, settings, _, _ = language_data
    scope = RagScope.model_validate_json(json.dumps(bindings["en"]["scope"]))
    scope.owner = "unrelated-owner"
    with pytest.raises(AgentFailure) as exc:
        async with rag_session(settings, scope, goal="How should API keys be rotated?"):
            pytest.fail("An unauthorized corpus must not open")
    assert exc.value.error.code == "DOCUMENT_NOT_AUTHORIZED"
