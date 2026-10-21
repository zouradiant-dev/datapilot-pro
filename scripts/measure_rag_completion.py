"""One explicitly authorized, bounded live run. Export metadata only; never auto-retry."""

import argparse
import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.orchestration.contracts import EvidenceRef
from datapilot.persistence.backend import Backend, DurableArtifacts, execute
from datapilot.persistence.session import run_async, run_durable
from datapilot.rag.cli import read_scope

ROOT = Path(__file__).resolve().parents[1]
QUESTION = "仅检索客户入门培训相关文档片段，保留实际来源引用"


async def measure(scope_path, destination):
    destination = destination.resolve()
    if not destination.is_relative_to(ROOT / "artifacts"):
        raise ValueError("Write only a new private artifacts/ measurement")
    destination.parent.mkdir(parents=True, exist_ok=True)
    id_ = str(uuid4())
    # An existing/incomplete measurement is a stop condition, never a retry trigger.
    with destination.open("x", encoding="utf-8") as stream:
        json.dump({"status": "started", "run_id": id_}, stream)
    settings = Settings(
        llm_mode="live",
        max_model_calls=8,
        max_total_tokens=18000,
        max_worker_turns=6,
        max_replans=0,
        context_allow_summary=False,
    )
    started = time.perf_counter()
    try:
        result = await run_durable(settings, id_, QUESTION, rag_scope=read_scope(scope_path))
        task_errors = [v.error.code for v in result["results"].values() if v.error]
    except AgentFailure as exc:
        result = {"status": "failed", "results": {}}
        task_errors = [exc.error.code]
    elapsed = (time.perf_counter() - started) * 1000
    backend = Backend(settings.runtime_database_url.get_secret_value(), id_, "local-user")
    try:
        with backend.transaction() as conn:
            rows = (
                execute(
                    conn,
                    "SELECT kind,tool_name,status,usage,elapsed_ms,payload "
                    "FROM execution.calls WHERE run_id=:run ORDER BY call_key",
                    run=id_,
                )
                .mappings()
                .all()
            )
        models = [r for r in rows if r["kind"] == "model"]
        payloads = [
            (r, json.loads(r["payload"]["ordered_json"]))
            for r in rows
            if r["kind"] == "tool" and r["payload"] and "ordered_json" in r["payload"]
        ]
        store = DurableArtifacts(backend)
        sources = []
        embeddings = {}
        for row, payload in payloads:
            if row["tool_name"] == "search_documents":
                for raw_ref in payload.get("artifact_refs", []):
                    ref = EvidenceRef.model_validate(raw_ref)
                    usage = store.get(ref).documents.embedding_usage
                    embeddings[ref.artifact_id] = usage.model_dump() if usage else None
        for task in result["results"].values():
            if not task.rag_completion:
                continue
            for ref in task.evidence_refs:
                artifact = store.get(ref)
                for doc in artifact.documents.documents:
                    if doc.document_id not in task.rag_completion.relevant_chunk_ids:
                        continue
                    source = ROOT / "tests/fixtures/rag" / doc.source
                    if doc.source not in {"onboarding.md", "billing.md", "release.md"}:
                        raise ValueError("This measurement approves synthetic sources only")
                    raw = source.read_bytes()
                    assert hashlib.sha256(raw).hexdigest() == doc.citation.source_sha256
                    assert (
                        raw.decode("utf-8-sig")[doc.citation.start : doc.citation.end] == doc.text
                    )
                    sources.append(
                        {
                            "source": doc.source,
                            "citation": doc.citation.model_dump(mode="json"),
                            "artifact_id": ref.artifact_id,
                        }
                    )
        completion = result.get("completion")
        report = {
            "run_id": id_,
            "protocol": "rag-submit-v1",
            "question": QUESTION,
            "kind": "real_deepseek_real_pg_real_local_embedding_mcp",
            "provider": settings.model_provider,
            "model": settings.model,
            "budget": {"max_runs": 1, "calls": 8, "tokens": 18000, "automatic_retries": 0},
            "status": result["status"],
            "completion": completion.model_dump() if completion else None,
            "accepted": bool(completion and completion.status == "completed" and sources),
            "error_codes": task_errors,
            "elapsed_ms": elapsed,
            "model_calls": [
                {"status": r["status"], "usage": r["usage"], "elapsed_ms": r["elapsed_ms"]}
                for r in models
            ],
            "total_model_calls": len(models),
            "total_reported_tokens": sum((r["usage"] or {}).get("total_tokens", 0) for r in models),
            "search_attempts": sum(r["tool_name"] == "search_documents" for r in rows),
            "search_executions": sum(
                r["tool_name"] == "search_documents" and not p.get("error") for r, p in payloads
            ),
            "context_reads": sum(r["tool_name"] == "read_context" for r in rows),
            "submission_attempts": sum(
                e.get("tool_name") == "submit_rag_result" for e in result.get("trace", [])
            ),
            "accepted_submissions": sum(
                r["tool_name"] == "submit_rag_result" and bool(p.get("rag_completion"))
                for r, p in payloads
            ),
            "stop_hook_corrections": sum(
                r["tool_name"] == "rag_completion_correction" for r in rows
            ),
            "sources": sources,
            "embedding_usage_by_artifact": embeddings,
            "receipts": [
                t.rag_completion.model_dump(mode="json")
                for t in result["results"].values()
                if t.rag_completion
            ],
            "raw_prompts_document_bodies_vectors_exported": False,
            "cost": {"amount": None, "reason": "no_invoice"},
        }
        destination.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    k: report[k]
                    for k in (
                        "run_id",
                        "status",
                        "accepted",
                        "error_codes",
                        "total_model_calls",
                        "total_reported_tokens",
                        "search_executions",
                        "stop_hook_corrections",
                    )
                },
                ensure_ascii=False,
            )
        )
        if not report["accepted"]:
            raise SystemExit(2)
    finally:
        backend.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true", required=True)
    args = parser.parse_args()
    run_async(measure(args.scope, args.output))


if __name__ == "__main__":
    main()
