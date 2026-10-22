"""Allowlist observability. No remote exporter, SQL, prompts, rows or document bodies."""

import json
from pathlib import Path

from datapilot.persistence.backend import Backend, execute
from datapilot.web.contracts import Observation


def export_local(records: list[Observation], path: Path):
    """Explicit local-only OTel SDK. Failure never changes execution or permissions."""
    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            SimpleSpanProcessor,
            SpanExporter,
            SpanExportResult,
        )

        class LocalExporter(SpanExporter):
            failed = False

            def export(self, spans):
                try:
                    with path.open("a", encoding="utf-8") as output:
                        for span in spans:
                            output.write(json.dumps(dict(span.attributes)) + "\n")
                    return SpanExportResult.SUCCESS
                except OSError:
                    self.failed = True
                    return SpanExportResult.FAILURE

        provider = TracerProvider()
        exporter = LocalExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        tracer = provider.get_tracer("datapilot.safe-local")
        for record in records:
            with tracer.start_as_current_span(
                "datapilot.call",
                attributes={k: v for k, v in record.model_dump().items() if v is not None},
            ):
                pass
        provider.shutdown()
        return not exporter.failed
    except Exception:
        return False


def public_trace(settings, run_id, policy):
    backend = Backend(settings.runtime_database_url.get_secret_value(), run_id, policy.owner)
    try:
        with backend.transaction() as conn:
            calls = (
                execute(
                    conn,
                    "SELECT call_key,kind,account,status,elapsed_ms,usage "
                    "FROM execution.calls WHERE run_id=:r ORDER BY call_key LIMIT 256",
                    r=run_id,
                )
                .mappings()
                .all()
            )
            events = (
                execute(
                    conn,
                    "SELECT payload FROM execution.events WHERE run_id=:r "
                    "ORDER BY event_id LIMIT 2048",
                    r=run_id,
                )
                .scalars()
                .all()
            )
            refs = (
                execute(
                    conn,
                    "SELECT artifact_id,task_id,plan_version,"
                    "payload->'metric'->>'evidence_id' AS evidence,"
                    "payload->'metric'->'verification'->>'verification_id' AS verification "
                    "FROM execution.artifacts WHERE run_id=:r ORDER BY artifact_id LIMIT 96",
                    r=run_id,
                )
                .mappings()
                .all()
            )
        records = []
        for call in calls:
            # Logical key includes only account/hash/call ID. Reject untrusted ID text.

            from datapilot.ingestion.common import digest

            key = digest({"logical_call_id": call["call_key"]})
            usage = call["usage"] or {}
            version, _, task = call["account"].partition(":")
            records.append(
                Observation(
                    run_id=run_id,
                    plan_version=int(version) if version.isdigit() else None,
                    task_id=task or None,
                    model_call=key if call["kind"] == "model" else None,
                    tool_call_id=key if call["kind"] == "tool" else None,
                    call_attempt_id=key,
                    latency_ms=float(call["elapsed_ms"] or 0),
                    status=call["status"],
                    provider_id=settings.model_provider if settings.llm_mode == "live" else "mock",
                    model_id=settings.model if settings.llm_mode == "live" else "scripted-fake",
                    endpoint_alias="configured_local_host",
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    cache_read_tokens=(usage.get("input_token_details") or {}).get("cache_read"),
                )
            )
        for ref in refs:
            records.append(
                Observation(
                    run_id=run_id,
                    plan_version=ref["plan_version"],
                    task_id=ref["task_id"],
                    artifact_id=ref["artifact_id"],
                    p3_evidence_id=ref["evidence"],
                    p3_verification_id=ref["verification"],
                )
            )
        routes = []
        for event in events:
            route = {
                k: event[k]
                for k in ("node", "status", "task_id", "plan_version", "worker")
                if k in event and isinstance(event[k], (str, int))
            }
            task = route.get("task_id")
            if task and ":" in task and task.split(":", 1)[0].isdigit():
                task = task.split(":", 1)[1]
                route["task_id"] = task
            if event.get("tool_call_id") and task and event.get("plan_version"):
                route["tool_call_id"] = digest(
                    {
                        "logical_call_id": f"tool:{event['plan_version']}:{task}:"
                        f"{event['tool_call_id']}"
                    }
                )
            route["artifact_ids"] = [
                s for s in event.get("evidence_ids", []) if isinstance(s, str) and len(s) == 64
            ]
            route["latency_ms"] = event.get("elapsed_ms", 0)
            routes.append(route)
        exported = None
        if policy.telemetry == "local":
            exported = export_local(records, policy.data_dir / "observations.jsonl")
        return {
            "schema_version": "api-v1",
            "run_id": run_id,
            "usage_source": "provider" if settings.llm_mode == "live" else "mock",
            "calls": [r.model_dump(exclude_none=True) for r in records],
            "routes": routes,
            "journal_replay_is_provider_cache": False,
            "cost": {"amount": None, "status": "price_and_invoice_not_available"},
            "remote_telemetry": False,
            "local_export_succeeded": exported,
        }
    finally:
        backend.close()
