"""Read official graph state without invoking nodes, recovery or external model calls."""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy.engine import make_url

from datapilot.contracts import AgentFailure
from datapilot.ingestion.common import digest
from datapilot.orchestration.budget import BudgetLedger
from datapilot.orchestration.contracts import BudgetLimits
from datapilot.orchestration.coordinator import Coordinator
from datapilot.persistence.backend import Backend, DurableArtifacts, execute
from datapilot.persistence.journal import Journal
from datapilot.persistence.session import fingerprint, serializer
from datapilot.rag.mcp import rag_session
from datapilot.reporting.service import report_session
from datapilot.runtime.mcp_client import database_session


class NoModel:
    async def respond(self, *args, **kwargs):
        raise AssertionError("Read-only inspection must never invoke a model")


async def control_state(settings, run_id, owner, question):
    """Read execution control only. Revoked data access must not prevent cancellation.

    This deliberately returns neither evidence nor report and never reauthorizes data.
    """
    backend = Backend(settings.runtime_database_url.get_secret_value(), run_id, owner)
    try:
        with backend.engine.connect() as conn:
            exists = execute(conn, "SELECT 1 FROM execution.runs WHERE run_id=:r", r=run_id).first()
        if not exists:
            return "pending", False
        with backend.transaction() as conn:
            manifest = backend.authorize(conn)["manifest"]
        if manifest["question"] != question:
            raise AgentFailure("RECOVERY_IDENTITY", "Control request has a different goal")
        url = make_url(settings.runtime_database_url.get_secret_value()).set(
            drivername="postgresql"
        )
        async with AsyncPostgresSaver.from_conn_string(
            url.render_as_string(hide_password=False), serde=serializer()
        ) as saver:
            engine = Coordinator(settings, NoModel(), checkpointer=saver)
            snapshot = await engine.graph.aget_state({"configurable": {"thread_id": run_id}})
            state = snapshot.values
            if state and (state.get("run_id"), state.get("question")) != (run_id, question):
                raise AgentFailure("RECOVERY_IDENTITY", "Control checkpoint identity differs")
            status = state.get("status", "pending")
            return status, bool(
                state
                and not snapshot.next
                and not snapshot.interrupts
                and status in {"succeeded", "failed", "cancelled", "unavailable"}
            )
    finally:
        backend.close()


async def inspect_run(settings, run_id, owner, question, *, report_scope=None, rag_scope=None):
    backend = Backend(settings.runtime_database_url.get_secret_value(), run_id, owner)
    try:
        with backend.transaction() as conn:
            manifest = backend.authorize(conn)["manifest"]
            calls = (
                execute(conn, "SELECT * FROM execution.calls WHERE run_id=:run", run=run_id)
                .mappings()
                .all()
            )
        if manifest["question"] != question:
            raise AgentFailure("RECOVERY_IDENTITY", "Goal differs from host authorization")
        limits = BudgetLimits(calls=settings.max_model_calls, tokens=settings.max_total_tokens)
        ledger, store = BudgetLedger(limits), DurableArtifacts(backend)
        with backend.transaction() as conn:
            stored = execute(
                conn, "SELECT payload FROM execution.ledger WHERE run_id=:r", r=run_id
            ).scalar_one()
        if digest(stored["state"]) != stored["sha256"]:
            raise AgentFailure("BUDGET_INVALID", "Stored budget hash changed")
        ledger.load_state(stored["state"])
        if ledger.accounts["root"].limits != limits:
            raise AgentFailure("BUDGET_INVALID", "Host budget policy changed")
        ledger.receipts = dict(stored["state"].get("receipts", {}))
        unknown = False
        for call in calls:
            if call["status"] in {"issued", "uncertain"}:
                unknown = True
            elif digest(call["payload"]) != call["payload_hash"]:
                raise AgentFailure("RECOVERY_CORRUPT", "External result hash changed")
            if call["kind"] == "model" and call["status"] == "complete":
                receipt = ledger.receipts.get(call["ticket"])
                actual = (call["usage"] or {}).get("total_tokens")
                actual = actual if type(actual) is int and actual >= 0 else None
                if not receipt or receipt[:2] != ["settled", actual]:
                    raise AgentFailure("BUDGET_INVALID", "Call settlement differs from ledger")
        url = make_url(settings.runtime_database_url.get_secret_value()).set(
            drivername="postgresql"
        )
        async with (
            AsyncPostgresSaver.from_conn_string(
                url.render_as_string(hide_password=False), serde=serializer()
            ) as saver,
            database_session(settings) as tools,
            report_session(settings, report_scope, question, owner) as reporting,
            rag_session(
                settings,
                rag_scope,
                goal=reporting.rag_question if reporting else question,
                **(
                    {"source_goals": reporting.scope.document_goal.source_goals}
                    if reporting
                    and reporting.scope.document_goal
                    and reporting.scope.document_goal.source_goals
                    else {}
                ),
            ) as retrieval,
        ):
            fresh = fingerprint(
                settings, question, owner, await tools.schema(), {}, manifest["review_required"]
            )
            if reporting:
                fresh["cross_source_report"] = reporting.manifest()
            if rag_scope:
                from datapilot.orchestration.rag_completion import retrieval_goal

                fresh.update(
                    rag_completion_protocol="rag-submit-v1",
                    rag_completion_goal=retrieval_goal(
                        reporting.rag_question if reporting else question,
                        retrieval,
                        reporting.scope if reporting else None,
                    ),
                    rag_scope=rag_scope.model_dump(mode="json"),
                    rag_sources=retrieval.context_scope().model_dump(mode="json"),
                )
            with backend.transaction() as conn:
                backend.authorize(conn, fresh)
            journal = Journal(backend, ledger, store)
            journal.require_review = manifest["review_required"]
            engine = Coordinator(
                settings,
                NoModel(),
                database=tools,
                retrieval=retrieval,
                run_id=run_id,
                checkpointer=saver,
                reporting=reporting,
                durability=journal,
            )
            engine.question = question
            current = await engine.graph.aget_state({"configurable": {"thread_id": run_id}})
            state = dict(current.values)
            # A concurrently finishing worker must not publish a newer checkpoint against
            # an older artifact/P3 bridge snapshot. Committed checkpoint references exist
            # before this subsequent read; a stale nonterminal snapshot publishes no report.
            artifacts = store.export()
            if reporting:
                await reporting.refresh(artifacts.values())
            if state and (state.get("run_id"), state.get("question")) != (run_id, question):
                raise AgentFailure("RECOVERY_IDENTITY", "Checkpoint identity differs")
            engine.plans = {int(k): v for k, v in state.get("plan_history", {}).items()}
            engine.reused = dict(state.get("reuse_origins", {}))
            report = None
            # A running child may be ahead of the parent snapshot. Never publish it yet.
            if not current.next and state:
                for result in state.get("results", {}).values():
                    if result.run_id != run_id:
                        raise AgentFailure("RECOVERY_IDENTITY", "Wrong task owner")
                    for ref in result.evidence_refs:
                        store.get(ref)
                    if result.status == "succeeded":
                        plan = engine.plans.get(result.plan_version)
                        task = (
                            next((t for t in plan.tasks if t.task_id == result.task_id), None)
                            if plan
                            else None
                        )
                        if (
                            task is None
                            or engine.verify(
                                {**state, "plan_version": result.plan_version}, task, result
                            ).status
                            != "passed"
                        ):
                            raise AgentFailure("RECOVERY_IDENTITY", "Restored proof failed")
                        for ref in result.evidence_refs:
                            if store.get(ref).report:
                                report = store.get(ref).report
            return {
                "state": state,
                "next": bool(current.next),
                "review": bool(current.interrupts),
                "unknown": unknown,
                "usage": ledger.snapshot().model_dump(),
                "report": report,
            }
    finally:
        backend.close()
