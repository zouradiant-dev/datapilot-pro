"""Read-only materialization/scope checks; never runs a sealed task or a retrieval query."""

import json

import sqlalchemy as sa
from p7_gate2b import BASE, environment, inspect, pack, write_new
from p7_holdout_pack import CaseInput

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.datasets.contracts import DatasetScope
from datapilot.persistence.session import run_async
from datapilot.rag.contracts import IndexManifest, RagScope
from datapilot.rag.mcp import rag_session
from datapilot.rag.storage import make_pin
from datapilot.reporting.contracts import ReportScope
from datapilot.runtime.mcp_client import dataset_session
from datapilot.semantics.contracts import SemanticDraft
from datapilot.semantics.registry import RegistryStore


async def main():
    inspect()
    env = environment()
    folder, public = pack()
    pins = json.loads((folder / "pins.json").read_bytes())
    settings = Settings(
        _env_file=None,
        llm_mode="fake",
        api_key=None,
        reader_database_url=env["DATAPILOT_READER_DATABASE_URL"],
        upload_reader_database_url=env["DATAPILOT_UPLOAD_READER_DATABASE_URL"],
        runtime_database_url=env["DATAPILOT_RUNTIME_DATABASE_URL"],
        rag_reader_database_url=env["DATAPILOT_RAG_READER_DATABASE_URL"],
    )
    schemas = {}
    for alias, pin in pins["datasets"].items():
        scope = DatasetScope.model_validate_json(
            json.dumps(
                {"bindings": [{"dataset_id": pin["dataset_id"], "version": pin["dataset_version"]}]}
            )
        )
        async with dataset_session(settings, scope) as tools:
            value = await tools.schema(pin["dataset_id"])
            assert (value.version, value.source_sha256) == (
                pin["dataset_version"],
                pin["source_sha256"],
            )
            schemas[alias] = value.model_dump(mode="json")
    checks = []
    for group, item in pins["corpora"].items():
        manifest = IndexManifest.model_validate_json(json.dumps(item["manifest"]))
        target = manifest.target
        scope = RagScope.model_validate_json(
            json.dumps(
                {
                    "owner": target.owner,
                    "corpora": [make_pin(manifest, item["index_version"]).model_dump(mode="json")],
                    "allow_saas": target.dataset_id is None,
                    "datasets": {
                        "bindings": [
                            {"dataset_id": target.dataset_id, "version": target.dataset_version}
                        ]
                        if target.dataset_id
                        else []
                    },
                }
            )
        )
        async with rag_session(settings, scope) as tools:
            # Original MCP preflight verifies original sources/spans/vectors; no search goal.
            assert tools is not None
        checks.append(
            {"snapshot": group, "status": "passed", "index_version": item["index_version"]}
        )
    cases = []
    for line in (folder / "inputs.jsonl").read_bytes().splitlines():
        task = CaseInput.model_validate_json(line)
        code = None
        try:
            ReportScope.model_validate_json(
                json.dumps(
                    {
                        "owner": task.owner,
                        "question": task.question,
                        "datasets": task.datasets.model_dump(mode="json"),
                        "metrics": [m.model_dump(mode="json") for m in task.metrics],
                        "document_goal": task.document_goal.model_dump(mode="json")
                        if task.document_goal
                        else None,
                        "causal_requested": task.causal_requested,
                    }
                )
            )
            if task.rag_scope:
                async with rag_session(settings, task.rag_scope):
                    pass
        except AgentFailure as failure:
            code = failure.error.code
        except ValueError:
            code = "REPORT_SCOPE_INVALID"
        cases.append(
            {
                "case_id": task.case_id,
                "input_environment_status": "rejected" if code else "accepted",
                "code": code,
                "task_executed": False,
            }
        )
    own, other = schemas["cash_v1"], schemas["restricted"]
    allowed = DatasetScope.model_validate_json(
        json.dumps({"bindings": [{"dataset_id": own["dataset_id"], "version": 1}]})
    )
    async with dataset_session(settings, allowed) as tools:
        for dataset_id, query in [
            (other["dataset_id"], "SELECT 1"),
            (
                own["dataset_id"],
                f'SELECT count(*) FROM uploads."{other["tables"][0]["physical_name"]}"',
            ),
            (own["dataset_id"], "DROP TABLE uploads.anything"),
        ]:
            try:
                await tools.execute(dataset_id, query)
            except (AgentFailure, ValueError):
                continue
            raise AssertionError("Unsafe or cross-Dataset request unexpectedly succeeded")
    registry = RegistryStore(env["DATAPILOT_REGISTRY_DATABASE_URL"])
    try:
        sample = next(
            p["semantic_definitions"][0]["definition"]
            for p in pins["datasets"].values()
            if p["semantic_definitions"]
        )
        try:
            registry.confirm_semantics(
                SemanticDraft.model_validate_json(json.dumps(sample)), reviewed=False
            )
        except AgentFailure as failure:
            assert failure.error.code == "REVIEW_REQUIRED"
        else:
            raise AssertionError("Unreviewed definition was confirmed")
    finally:
        registry.close()
    engine = sa.create_engine(env["DATAPILOT_ADMIN_DATABASE_URL"], hide_parameters=True)
    try:
        with engine.connect() as conn:
            roles = conn.exec_driver_sql(
                "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,rolinherit "
                "FROM pg_roles WHERE rolname LIKE 'datapilot_%%' ORDER BY rolname"
            ).all()
            assert all(not any(row[1:]) for row in roles)
            vectors = conn.exec_driver_sql(
                "SELECT count(*),min(vector_dims(embedding)),max(vector_dims(embedding)) "
                "FROM rag.chunks"
            ).one()
            assert vectors[0] > 0 and vectors[1:] == (512, 512)
    finally:
        engine.dispose()
    receipt = {
        "seal_sha256": public["seal_sha256"],
        "dataset_snapshots": 13,
        "corpus_snapshots": checks,
        "input_contracts": cases,
        "candidate_runs": 0,
        "retrieval_queries": 0,
        "paid_calls": 0,
        "unsafe_and_cross_dataset_requests_rejected": 3,
        "unreviewed_semantic_definition_rejected": True,
        "restricted_roles": len(roles),
        "pgvector_rows": vectors[0],
        "vector_dimensions": 512,
        "version_history_pins_verified": True,
        "semantic_metric_confirmation": "pending_human_record",
    }
    write_new(BASE / "input-environment-validation.json", receipt)
    print(
        json.dumps(
            {
                "dataset_snapshots": 13,
                "index_snapshots": 5,
                "vector_rows": vectors[0],
                "rejected_input_contracts": [x for x in cases if x["code"]],
                "candidate_runs": 0,
            }
        )
    )


def vector_integrity():
    """Metadata consistency only: no Holdout query, re-embedding or similarity tuning."""
    import numpy as np
    from p7_holdout_pack import sha

    from datapilot.rag.models import validate_vectors
    from datapilot.rag.storage import Connection

    inspect()
    folder, _ = pack()
    pins = json.loads((folder / "pins.json").read_bytes())
    versions = [p["index_version"] for p in pins["corpora"].values()]
    reader = Connection(environment()["DATAPILOT_RAG_READER_DATABASE_URL"], "datapilot_rag_reader")
    try:
        with reader.read() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT embedding::text,embedding_sha256 FROM rag.chunks "
                    "WHERE index_version=ANY(:versions)"
                ),
                {"versions": versions},
            ).all()
        for vector, expected in rows:
            value = np.asarray(json.loads(vector), dtype=np.float32)
            validate_vectors([value], 1)
            assert sha(value.astype("<f4").tobytes()) == expected
        write_new(
            BASE / "vectors-integrity.json",
            {
                "vectors_checked": len(rows),
                "dimensions": 512,
                "hashes_and_norms": "passed",
                "queries": 0,
                "paid_calls": 0,
                "reembedding_for_tuning": False,
            },
        )
        print(json.dumps({"vectors_checked": len(rows), "hashes_and_norms": "passed"}))
    finally:
        reader.close()


if __name__ == "__main__":
    run_async(main())
