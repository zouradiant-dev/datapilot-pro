"""Versioned pilot files and trusted synthetic host bindings, not a new runtime."""

import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from datapilot.datasets.contracts import DatasetBinding, DatasetScope
from datapilot.ingestion.common import digest
from datapilot.rag.contracts import ChunkCitation, Chunker, IndexManifest, Limits, RagScope, Target
from datapilot.rag.models import specification
from datapilot.rag.parsing import parse_sources
from datapilot.rag.storage import policy_hash
from datapilot.reporting.contracts import (
    CitationPolicy,
    CitationSource,
    DocumentFact,
    DocumentGoal,
    ReportScope,
)
from datapilot.semantics.contracts import MetricRequest, MetricWindow

from .contracts import Pilot

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/p7/qwen-business-pilot-v1"
HERE = Path(__file__).parent
ARMS = {"bge": None, "qwen": "qwen3-cuda-fp16-v1"}


def load():
    return Pilot.model_validate_json((HERE / "cases.json").read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(value, ensure_ascii=False, indent=2).encode()
    with path.open("xb") as stream:
        stream.write(body)


def corpus_id(case):
    return str(uuid5(NAMESPACE_URL, "datapilot:phase2c-business-v1:" + case.id))


def run_id(case, arm):
    return str(uuid5(NAMESPACE_URL, "datapilot:phase2c-business-v1:" + arm + ":" + case.id))


def dataset_scope(case):
    p = load()
    return DatasetScope(
        bindings=[
            DatasetBinding(
                dataset_id=str(uuid5(NAMESPACE_URL, "datapilot:local:" + p.dataset_name)), version=1
            )
        ]
        if case.metric
        else []
    )


def manifest(case, arm):
    """Pure local parsing; constructing a manifest performs NO vector inference/search."""
    p = load()
    scope = RagScope(
        owner=p.owner,
        allow_saas=not case.metric,
        datasets=dataset_scope(case),
        embedding_profile=ARMS[arm],
    )
    target = Target(
        corpus_id=corpus_id(case),
        owner=p.owner + "-foreign" if case.foreign_owner else p.owner,
        dataset_id=scope.datasets.bindings[0].dataset_id if case.metric else None,
        dataset_version=1 if case.metric else None,
    )
    parsed = parse_sources(
        sorted((OUT / "sources" / case.id).glob("*.md")),
        target.corpus_id,
        Chunker(),
        Limits(),
    )
    return IndexManifest(
        target=target,
        model=specification(ARMS[arm]),
        chunker=Chunker(),
        sources=sorted([s.info for s in parsed], key=lambda s: s.source_id),
        relevance_policy_sha256=policy_hash(scope),
    )


def scopes(case, arm, binding):
    p = load()
    m = IndexManifest.model_validate_json(json.dumps(binding[case.id][arm]["manifest"]))
    from datapilot.rag.storage import make_pin

    rag = RagScope(
        owner=p.owner,
        corpora=[make_pin(m, digest(m))],
        datasets=dataset_scope(case),
        allow_saas=not case.metric,
        embedding_profile=ARMS[arm],
    )

    def citation(name, quote=None):
        source = next(s for s in m.sources if s.name == name)
        text = (OUT / "sources" / case.id / name).read_text(encoding="utf-8")
        span = next(s for s in source.chunks if quote is None or quote in text[s.start : s.end])
        return ChunkCitation(
            **span.model_dump(),
            corpus_id=m.target.corpus_id,
            index_version=digest(m),
            source_id=source.source_id,
            document_id=source.document_id,
            version=source.version,
            source_sha256=source.version,
            model_revision=m.model.revision,
            chunker_sha256=digest(m.chunker),
            score=0,
        )

    def facts(rows):
        return [
            DocumentFact(
                fact_id=id_,
                description="Pre-registered synthetic literal fact; not model approval",
                **(
                    {
                        "citation": citation(name, quote),
                        "quotation": quote,
                        "confirmation_ref": "public-pilot-test-host-v1:" + case.id,
                    }
                    if name
                    else {}
                ),
            )
            for id_, name, quote in rows
        ]

    metrics = []
    if case.metric:
        metadata = binding["metric"]
        metrics = [
            MetricRequest(
                goal_id="revenue",
                dataset_id=rag.datasets.bindings[0].dataset_id,
                dataset_version=1,
                semantic_version=metadata["semantic"]["semantic_version"],
                metric_version=metadata["metric"]["metric_version"],
                metric_id="paid_invoice_revenue",
                window=MetricWindow.model_validate_json(
                    json.dumps(
                        {
                            "start": p.metric_gold["start"],
                            "end_exclusive": p.metric_gold["end_exclusive"],
                        }
                    )
                ),
            )
        ]
    report = ReportScope(
        owner=p.owner,
        question=case.query,
        datasets=rag.datasets,
        metrics=metrics,
        document_goal=DocumentGoal(
            goal_id="documents",
            question=case.doc_query or case.query,
            metric_goals=[r.goal_id for r in metrics],
            purpose="facts",
            required_facts=facts(case.facts),
        ),
        causal_requested=case.causal,
        partial_evidence_policy="partial-facts-v1",
        rag_query_policy="original-first-v1",
        citation_policy=CitationPolicy(
            goal_sha256=hashlib.sha256(case.query.encode()).hexdigest(),
            required_sources=[
                CitationSource(
                    **citation(name).model_dump(include=set(CitationSource.model_fields))
                )
                for name in case.required
            ],
            supplementary_claims=facts(case.supplementary),
        ),
    )
    return rag, report
