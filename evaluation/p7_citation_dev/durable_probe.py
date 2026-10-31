"""Original Durable path with scripted decisions; candidate is read-only Dev projection."""

import argparse
import json
import sys
from uuid import NAMESPACE_URL, uuid5

from dev import OUT, OWNER, ROOT, cases, environment, host_scope, source_ids

sys.path.insert(0, str(ROOT / "scripts"))
from candidate import project  # noqa: E402
from report_recovery_probe import ReportDecisions  # noqa: E402
from v3_common import write_new  # noqa: E402

from datapilot.ingestion.common import digest  # noqa: E402
from datapilot.orchestration.contracts import BudgetLimits, TaskEnvelope, TaskSpec  # noqa: E402
from datapilot.persistence.backend import Backend, DurableArtifacts, execute  # noqa: E402
from datapilot.persistence.session import run_async, run_durable  # noqa: E402
from datapilot.rag.mcp import rag_session  # noqa: E402
from datapilot.reporting.service import report_session  # noqa: E402


class InsufficientScript(ReportDecisions):
    async def respond(self, messages, tools):
        result = await super().respond(messages, tools)
        for call in result.tool_calls:
            if call["name"] == "search_documents":
                call["args"]["top_k"] = 5
            if call["name"] == "submit_rag_result":
                call["args"]["outcome"] = "insufficient"
        return result


class NoModel:
    async def respond(self, *_):
        raise AssertionError("Recovery cannot reissue a settled model call")


async def probe(action):
    _, settings = environment()
    case = next(c for c in cases() if c["id"] == "cp06")
    binding = json.loads((OUT / "bindings.json").read_bytes())["bindings"]["cp06"]
    rag, scope = host_scope(case, binding)
    run_id = str(uuid5(NAMESPACE_URL, OWNER + ":durable-cp06"))
    result = await run_durable(
        settings,
        run_id,
        scope.question if action == "start" else None,
        resume=action != "start",
        owner=OWNER,
        report_scope=scope,
        rag_scope=rag,
        transport=InsufficientScript(scope.question) if action == "start" else NoModel(),
    )
    backend = Backend(settings.runtime_database_url.get_secret_value(), run_id, OWNER)
    try:
        store = DurableArtifacts(backend)
        task = result["results"]["1:documents"]
        assert (
            task.status == "unavailable"
            and task.rag_completion.submission.outcome == "insufficient"
        )
        refs = task.evidence_refs
        pairs = [(ref, store.get(ref)) for ref in refs]
        assert pairs and result["cross_source_report"].business_completion.status == "unavailable"
        envelope = TaskEnvelope(
            run_id=run_id,
            plan_version=1,
            task=TaskSpec(task_id="documents", worker="rag", instruction=scope.question),
            allowed_tools=["search_documents", "submit_rag_result"],
            budget=BudgetLimits(),
            parent_id=run_id,
        )
        async with rag_session(settings, rag, goal=scope.question) as retrieval:
            async with report_session(settings, scope, scope.question, OWNER) as service:
                view = project(
                    service,
                    pairs,
                    retrieval,
                    envelope,
                    store,
                    task.rag_completion.submission,
                    source_ids(case, binding),
                )
        assert view.status == "partial" and view.supported_facts == ["identity"]
        with backend.transaction() as conn:
            calls = [
                dict(r)
                for r in execute(
                    conn,
                    "SELECT call_key,kind,status,payload_hash FROM execution.calls "
                    "WHERE run_id=:r ORDER BY call_key",
                    r=run_id,
                ).mappings()
            ]
        assert all(c["status"] == "complete" for c in calls)
        record = {
            "run_id": run_id,
            "artifact_export_sha256": digest(
                {key: value.model_dump(mode="json") for key, value in store.export().items()}
            ),
            "report_sha256": digest(result["cross_source_report"]),
            "usage": result["usage"].model_dump(mode="json")
            if hasattr(result["usage"], "model_dump")
            else result["usage"],
            "calls": calls,
            "receipt_sha256": digest(task.rag_completion),
            "candidate": view.model_dump(mode="json"),
            "candidate_sha256": digest(view),
            "provider_calls": 0,
            "candidate_durable_storage": "design_only_not_written",
        }
        if action == "resume":
            previous = json.loads((OUT / "durable-start.json").read_bytes())
            assert record == previous, "Recovery changed settled evidence, budget or view"
        suffix = (
            "start" if action in {"start", "capture"} else "resume-py" + str(sys.version_info.minor)
        )
        write_new(OUT / ("durable-" + suffix + ".json"), record)
        print(
            "Original Durable",
            suffix,
            "settled refs/budget unchanged; Dev view=partial; paid calls=0",
        )
    finally:
        backend.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("start", "resume", "capture"))
    run_async(probe(parser.parse_args().action))
