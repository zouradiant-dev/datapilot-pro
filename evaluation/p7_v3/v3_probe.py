"""Unrelated synthetic protocol probe; never execute a formal case with Fake decisions."""

import json
import sys
import time
from pathlib import Path
from uuid import uuid4

from p7_business_scoring import sign_collection
from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from v3_common import (
    BASE,
    OWNER,
    PROFILE,
    ROOT,
    Answer,
    Case,
    infrastructure,
    parent_freeze,
    scope,
    write_new,
)
from v3_runner import container_action
from v3_score import score

from datapilot.data.semantic_demo import mapping_draft
from datapilot.datasets.contracts import DatasetBinding, DatasetScope, ImportRequest
from datapilot.datasets.repository import DatasetRepository
from datapilot.ingestion.common import digest
from datapilot.ingestion.confirmation import confirm_schema
from datapilot.ingestion.contracts import ParseOptions
from datapilot.ingestion.parser import parse_file
from datapilot.ingestion.profiling import propose_schema
from datapilot.ingestion.service import IngestionService
from datapilot.rag.contracts import ChunkCitation, RagScope, Target
from datapilot.rag.models import LocalEmbedding
from datapilot.rag.storage import IngestionService as RagIngest
from datapilot.rag.storage import make_pin
from datapilot.reporting.contracts import DocumentFact, DocumentGoal
from datapilot.semantics.contracts import MetricDraft, MetricRequest, SemanticDraft
from datapilot.semantics.registry import RegistryStore


class ProbeCase(Case):
    case_id: str = Field(pattern=r"^probe-v3-[a-z0-9-]+$")


class ProbeAnswer(Answer):
    case_id: str = Field(pattern=r"^probe-v3-[a-z0-9-]+$")


def prepare(values):
    directory = BASE / "private/probe"
    directory.mkdir(exist_ok=False)
    source = directory / "invoices.csv"
    source.write_text(
        (
            "invoice_id,customer_id,amount_cents,invoice_date,p"
            "ayment_status,currency\nprobe-i,probe-c,6407,2033-1"
            "0-03,paid,CNY\n"
        ),
        encoding="utf-8",
    )
    parsed = parse_file(source, options=ParseOptions(header="present"))
    ingest = IngestionService(
        values["DATAPILOT_INGEST_DATABASE_URL"], storage_dir=directory / "snapshots"
    )
    try:
        imported = ingest.import_file(
            source,
            confirm_schema(parsed, propose_schema(parsed), reviewed=True),
            ImportRequest(name="p7-v3-protocol-probe-only"),
        )
    finally:
        ingest.close()
    datasets = DatasetScope(
        bindings=[DatasetBinding(dataset_id=imported.dataset_id, version=imported.version)]
    )
    repo = DatasetRepository(values["DATAPILOT_UPLOAD_READER_DATABASE_URL"], datasets)
    try:
        schema = repo.schema(imported.dataset_id)
    finally:
        repo.close()
    registry = RegistryStore(values["DATAPILOT_REGISTRY_DATABASE_URL"])
    try:
        mapping = mapping_draft(schema).model_dump(mode="json")
        for entity in mapping["entities"]:
            entity.update(coverage_start="2033-01-01", coverage_end_exclusive="2034-01-01")
        semantic = registry.confirm_semantics(
            SemanticDraft.model_validate_json(json.dumps(mapping)), reviewed=True
        )
        metric = registry.confirm_metric(
            MetricDraft(
                dataset_id=imported.dataset_id,
                dataset_version=imported.version,
                semantic_version=1,
                metric_id="paid_invoice_revenue",
            ),
            reviewed=True,
        )
    finally:
        registry.close()
    text = (
        "# 合成协议探针\n合成协议探针不包含生产数据。"
        "账单收入只用于验证原 Runtime 接线。本说明没有承诺恢复时限。\n"
    )
    document = directory / "probe.md"
    document.write_text(text, encoding="utf-8")
    owner = OWNER + "-probe"
    rag = RagScope(owner=owner, datasets=datasets)
    ingestor = RagIngest(values["DATAPILOT_RAG_INGEST_DATABASE_URL"], LocalEmbedding())
    try:
        manifest, index, _, _ = ingestor.ingest(
            Target(
                corpus_id=str(uuid4()),
                owner=owner,
                dataset_id=imported.dataset_id,
                dataset_version=1,
            ),
            [document],
            scope=rag,
            reviewed=True,
        )
    finally:
        ingestor.close()
    rag.corpora = [make_pin(manifest, index)]
    src = manifest.sources[0]
    span = src.chunks[0]
    citation = ChunkCitation(
        **span.model_dump(),
        corpus_id=manifest.target.corpus_id,
        index_version=index,
        source_id=src.source_id,
        document_id=src.document_id,
        version=src.version,
        source_sha256=src.text_sha256,
        model_revision=manifest.model.revision,
        chunker_sha256=digest(manifest.chunker),
        score=0.0,
    )
    request = MetricRequest.model_validate_json(
        json.dumps(
            {
                "goal_id": "metric_1",
                "dataset_id": imported.dataset_id,
                "dataset_version": 1,
                "semantic_version": 1,
                "metric_id": "paid_invoice_revenue",
                "metric_version": 1,
                "window": {"start": "2033-10-01", "end_exclusive": "2033-11-01"},
            }
        )
    )
    cases = []
    for kind in ["completed", "partial", "unavailable"]:
        question = "检索包含“合成协议探针”的文档片段，保留来源引用。"
        facts = []
        if kind == "partial":
            facts.append(
                DocumentFact(
                    fact_id="known",
                    description="不含生产数据",
                    citation=citation,
                    quotation="合成协议探针不包含生产数据。",
                    confirmation_ref="synthetic-protocol-probe-only",
                )
            )
        if kind != "completed":
            facts.append(DocumentFact(fact_id="unknown", description="未承诺的恢复时限"))
        metrics = [request] if kind == "completed" else []
        goal = DocumentGoal(
            goal_id="documents",
            question=question,
            metric_goals=[m.goal_id for m in metrics],
            purpose="facts" if facts else "summary",
            required_facts=facts,
        )
        case = ProbeCase(
            case_id="probe-v3-" + kind,
            lane="sql_rag" if metrics else "rag_only",
            objective="unrelated-protocol-probe-" + kind,
            question=question,
            owner=owner,
            datasets=datasets,
            metrics=metrics,
            document_goal=goal,
            rag_scope=rag,
        )
        answer = ProbeAnswer(
            case_id=case.case_id,
            business_completion=kind,
            host_decision="review_then_run",
            metrics=[
                {"goal_id": "metric_1", "disposition": "verified", "value": "64.07", "unit": "CNY"}
            ]
            if metrics
            else [],
            retrieval={"facts": []},
            refusal_conditions=[],
            causal_claim_must_remain_unverified=False,
            expected_verdicts={"metric_1": "verified"} if metrics else {},
            missing_fact_ids=["unknown"] if facts else [],
        )
        cases.append((case, answer))
    pins = {
        "datasets": {
            "probe": {
                "schema": schema.model_dump(mode="json"),
                "semantics": semantic.model_dump(mode="json"),
                "metrics": [metric.model_dump(mode="json")],
            }
        }
    }
    write_new(
        directory / "fixtures.json",
        {
            "cases": [[c.model_dump(mode="json"), g.model_dump(mode="json")] for c, g in cases],
            "pins": pins,
        },
    )
    return directory, cases, pins


def main():
    values = infrastructure(ROOT / "artifacts/p7/unified-regression/private/environment.json")
    _, product = parent_freeze()
    directory = BASE / "private/probe"
    if (directory / "fixtures.json").exists():
        fixture = json.loads((directory / "fixtures.json").read_bytes())
        cases = [
            (
                ProbeCase.model_validate_json(json.dumps(t)),
                ProbeAnswer.model_validate_json(json.dumps(g)),
            )
            for t, g in fixture["cases"]
        ]
        pins = fixture["pins"]
    else:
        directory, cases, pins = prepare(values)
    key = b"protocol-probe-collector-key-not-live"
    records = []
    for task, gold in cases:
        folder = directory / task.case_id
        if (folder / "collection.json").exists():
            config = json.loads((folder / "config.json").read_bytes())
            first = json.loads((folder / "collection.json").read_bytes())
        else:
            folder.mkdir(exist_ok=False)
            config = {
                "case_id": task.case_id,
                "synthetic_probe": True,
                "owner": task.owner,
                "run_id": str(uuid4()),
                "question_sha256": digest(task.question),
                "profile": PROFILE,
                "report_scope": scope(task).model_dump(mode="json"),
                "rag_scope": task.rag_scope.model_dump(mode="json"),
            }
            write_new(folder / "config.json", config)
            for action in ["probe", "start", "approve"]:
                container_action(
                    config, folder, "fake", action, values, product, time.monotonic() + 180
                )
            first = container_action(
                config, folder, "fake", "collect", values, product, time.monotonic() + 180
            )
            write_new(folder / "collection.json", first)
        record = sign_collection(first, key)
        result = score(task, gold, record, key, pins)
        score_path = folder / "score.json"
        if score_path.exists():
            if json.loads(score_path.read_bytes()) != result:
                write_new(folder / "score-r2.json", result)
        else:
            write_new(score_path, result)
        assert result["strict_correct"], result
        if not (folder / "replay-process.json").exists():
            container_action(
                config, folder, "fake", "replay", values, product, time.monotonic() + 180
            )
        # Separate folder keeps the original collector output; same trusted config/Run identity.
        repeat = folder / "readonly-second-collector"
        if (repeat / "collection.json").exists():
            after = json.loads((repeat / "collection.json").read_bytes())
        else:
            repeat.mkdir()
            write_new(repeat / "config.json", config)
            after = container_action(
                config, repeat, "fake", "collect", values, product, time.monotonic() + 180
            )
        assert all(first[k] == after[k] for k in ["calls", "artifacts", "snapshot"])
        if not (repeat / "collection.json").exists():
            write_new(repeat / "collection.json", after)
        records.append(
            {
                "case_id": task.case_id,
                "run_id": config["run_id"],
                "strict_contract_correct": True,
                "NoModel_replay_unchanged": True,
                "fixture": True,
            }
        )
        print(task.case_id + " PG/MCP/Fake + NoModel replay passed", flush=True)
    write_new(
        directory / "summary.json",
        {
            "records": records,
            "paid_model_calls": 0,
            "formal_holdout_runs": 0,
            "fake_is_not_live_quality": True,
        },
    )


if __name__ == "__main__":
    main()
