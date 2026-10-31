"""Trusted Qwen opt-in Web confirmation, real local GPU/PG/MCP; no paid API."""

import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_cross_source_postgres import ReportDecisions
from test_rag_only_postgres import approve_and_run
from test_web_goal_confirmation_postgres import QUESTION, TEXT, candidate, confirm, session
from test_web_postgres import import_sample

from datapilot.rag.contracts import RagScope
from datapilot.rag.qwen import interpreter
from datapilot.rag.storage import Repository
from datapilot.runtime.mcp_client import server_environment
from datapilot.web.app import create_app
from datapilot.web.config import HostPolicy

pytestmark = pytest.mark.integration
ROOT = Path(__file__).parents[1]


def test_qwen_confirmation_original_worker_and_inspector(portable_pg, tmp_path):
    if os.getenv("DATAPILOT_RUN_QWEN_TESTS") != "1":
        pytest.skip("Explicit local CUDA opt-in required")
    policy = HostPolicy(
        secret="public-qwen-web-test",
        owner="qwen-web-" + uuid4().hex[:12],
        data_dir=tmp_path,
        api_host="testserver",
        ui_origin="http://localhost:8519",
        rag_embedding_profile="qwen3-cuda-fp16-v1",
    )
    app = create_app(policy=policy, settings=portable_pg, dispatch=False)
    folder = ROOT / "artifacts/tests" / ("qwen-web-" + uuid4().hex)
    folder.mkdir(parents=True)
    path = folder / "billing.md"
    path.write_text(TEXT, encoding="utf-8")
    with TestClient(app) as c:
        session(c, policy)
        metric = import_sample(c)
        m = metric["metrics"][0]
        env = server_environment(portable_pg)
        env.update(
            PYTHONPATH=str(ROOT / "src"),
            PYTHONUTF8="1",
            DATAPILOT_API_KEY="",
            DATAPILOT_LLM_MODE="fake",
            DATAPILOT_RAG_INGEST_DATABASE_URL=os.environ["DATAPILOT_RAG_INGEST_DATABASE_URL"],
            DATAPILOT_UPLOAD_READER_DATABASE_URL=(
                portable_pg.upload_reader_database_url.get_secret_value()
            ),
        )
        output = folder / "scope.json"
        result = subprocess.run(
            [
                interpreter(),
                "-m",
                "datapilot.cli",
                "rag",
                "ingest",
                "--corpus",
                str(uuid4()),
                "--file",
                str(path),
                "--owner",
                policy.owner,
                "--dataset",
                m["dataset_id"],
                "--dataset-version",
                str(m["dataset_version"]),
                "--reviewed",
                "--embedding-profile",
                "qwen3-cuda-fp16-v1",
                "--output",
                str(output),
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=150,
        )
        (folder / "ingest.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        assert result.returncode == 0, result.stderr[-600:]
        rag = RagScope.model_validate_json(output.read_bytes())
        repo = Repository(portable_pg.rag_reader_database_url.get_secret_value(), rag)
        try:
            manifest = next(iter(repo.manifests().values()))
        finally:
            repo.close()
        app.state.store.corpus(manifest.target, rag.corpora[0])
        host = (c, app, portable_pg, metric, {"corpus_id": manifest.target.corpus_id})
        cid, msg = candidate(host)
        id_ = confirm(host, cid, msg)
        payload = app.state.store.run(id_)["payload"]
        assert payload["rag_scope"]["embedding_profile"] == "qwen3-cuda-fp16-v1"
        approve_and_run(c, app, portable_pg, id_, transport=ReportDecisions(QUESTION))
        report = c.get(f"/api/v1/tasks/{id_}/report")
        assert report.status_code == 200, report.text
        assert report.json()["business_completion"]["status"] == "completed", report.text
        assert (
            report.json()["citations"][0]["citation"]["model_revision"] == manifest.model.revision
        )
        # Persist a reproducible result identity, not raw credentials or unrelated business rows.
        (folder / "result.json").write_text(
            json.dumps(
                {
                    "run_id": id_,
                    "report": report.json(),
                    "model": manifest.model.model_dump(mode="json"),
                }
            ),
            encoding="utf-8",
        )
