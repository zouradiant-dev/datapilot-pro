"""Offline protocol evidence, never a permission source or Runtime extension."""

import json
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from p7_business_scoring import authenticated  # noqa: E402

from datapilot.ingestion.common import digest  # noqa: E402
from datapilot.orchestration.contracts import Plan  # noqa: E402
from datapilot.orchestration.tools import SearchArguments  # noqa: E402

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Account = Annotated[str, Field(min_length=1, max_length=96)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Notice(Strict):
    protocol: Literal["rag-submit-v1"]
    reason: Literal[
        "COMPLETION_REQUIRED",
        "COMPLETION_BATCH_INVALID",
        "RAG_ATTEMPTS_EXHAUSTED",
        "RAG_OUTCOME_INVALID",
        "EVIDENCE_INSUFFICIENT",
        "INPUT_INVALID",
    ]
    trigger: Digest
    attempt: int = Field(ge=1, le=1)


class Call(Strict):
    run_id: str = Field(min_length=1, max_length=64)
    call_key: str = Field(min_length=1, max_length=256)
    fingerprint: Digest
    kind: Literal["model", "tool"]
    account: Account
    status: Literal["complete"]
    tool_name: str | None
    ticket: str | None
    payload: dict
    payload_hash: Digest
    elapsed_ms: float | None
    usage: dict | None


class Event(Strict):
    event_id: int = Field(ge=1)
    run_id: str
    payload: dict


class Transcript(Strict):
    account: Account
    thread_id: str
    checkpoint_id: str = Field(min_length=1, max_length=128)
    checkpoint_ns: str = Field(min_length=1, max_length=256)
    messages: list[dict] = Field(min_length=1, max_length=256)


class Witness(Strict):
    schema_version: Literal["p7-v4-journal-witness-1"]
    source: Literal["postgres-readonly-v1", "synthetic-dev-v1"]
    case_id: str
    run_id: str
    owner: str
    manifest_sha256: Digest
    collection_sha256: Digest
    calls: list[Call] = Field(max_length=512)
    events: list[Event] = Field(max_length=2048)
    transcripts: list[Transcript] = Field(max_length=24)


def unpack(row):
    body = row.payload
    if set(body) == {"ordered_json"} and isinstance(body["ordered_json"], str):
        result = json.loads(body["ordered_json"])
        if isinstance(result, dict):
            return result
    raise ValueError("Tool payload is not original ordered JSON")


def account_task(payload, account):
    version, task = account.split(":", 1)
    if not version.isdecimal() or str(int(version)) != version:
        raise ValueError("Invalid plan version")
    plan = Plan.model_validate(payload["snapshot"]["state"]["plan_history"][version])
    return int(version), next(t for t in plan.tasks if t.task_id == task)


def bootstrap_arguments(payload, row, task):
    state = payload["snapshot"]["state"]
    version = int(row.account.split(":", 1)[0])
    if row.tool_name == "p3_metric_execution":
        if task.worker != "sql" or row.call_key != "tool:" + row.account + ":metric":
            raise ValueError("Metric bootstrap identity")
        requests = payload["manifest"]["cross_source_report"]["scope"]["metrics"]
        request = next(r for r in requests if r["goal_id"] == task.task_id)
        return {"request": request}
    if row.tool_name != "verified_report_projection" or task.worker != "report":
        raise ValueError("Not a known trusted bootstrap")
    if row.call_key != "tool:" + row.account + ":report":
        raise ValueError("Report bootstrap identity")
    statuses, refs = {}, {}
    for dep in task.dependencies:
        key = f"{version}:{dep}"
        result, verification = state["results"][key], state["verifications"][key]
        status = "failed" if verification["status"] == "failed" else result["status"]
        statuses[dep] = status
        if status not in {"succeeded", "unavailable"} or (
            result["worker"] == "rag" and result["status"] != "succeeded"
        ):
            continue
        for ref in result["evidence_refs"]:
            refs[ref["artifact_id"]] = ref
    return {"inputs": list(refs.values()), "source_statuses": statuses}


def _verify(payload, proof):
    if (
        proof.case_id,
        proof.run_id,
        proof.owner,
        proof.manifest_sha256,
        proof.collection_sha256,
    ) != (
        payload["case_id"],
        payload["run_id"],
        payload["manifest"]["owner"],
        payload["manifest_sha256"],
        digest(payload),
    ) or digest(payload["manifest"]) != proof.manifest_sha256:
        raise ValueError("Witness identity differs")
    original = {r["call_key"]: r for r in payload["calls"]}
    calls = {r.call_key: r for r in proof.calls}
    if (
        len(calls) != len(proof.calls)
        or len(original) != len(payload["calls"])
        or calls.keys() != original.keys()
    ):
        raise ValueError("Duplicate/missing call")
    for key, row in calls.items():
        if row.run_id != proof.run_id or digest(row.payload) != row.payload_hash:
            raise ValueError("Journal identity/hash differs")
        if any(row.model_dump()[k] != value for k, value in original[key].items()):
            raise ValueError("Collector and persisted call differ")
    if [e.payload for e in proof.events] != payload["events"]:
        raise ValueError("Collector and persisted events differ")
    if any(e.run_id != proof.run_id for e in proof.events) or any(
        a.event_id >= b.event_id for a, b in zip(proof.events, proof.events[1:], strict=False)
    ):
        raise ValueError("Wrong/duplicate/out-of-order Journal event")
    sequences = [e.payload["sequence"] for e in proof.events if "sequence" in e.payload]
    if any(type(i) is not int for i in sequences) or any(
        a >= b for a, b in zip(sequences, sequences[1:], strict=False)
    ):
        raise ValueError("Trace sequence differs")
    if any(e.payload.get("run_id") != proof.run_id for e in proof.events):
        raise ValueError("Trace owner differs")
    expected, controls = {}, []
    for row in proof.calls:
        if row.kind == "model":
            if row.call_key != "model:" + row.account + ":" + row.fingerprint:
                raise ValueError("Model fingerprint differs")
            if row.payload.get("type") != "ai" or row.payload["data"].get("type") != "ai":
                raise ValueError("Model response is not assistant")
            if row.payload["data"].get("invalid_tool_calls"):
                raise ValueError("Malformed provider tool call")
            for tool in row.payload["data"].get("tool_calls", []):
                if set(tool) != {"id", "name", "args", "type"} or tool["type"] != "tool_call":
                    raise ValueError("Invalid native tool DTO")
                if not all(
                    isinstance(tool[k], str) and tool[k] for k in ["id", "name"]
                ) or not isinstance(tool["args"], dict):
                    raise ValueError("Invalid native tool identity")
                key = "tool:" + row.account + ":" + tool["id"]
                if key in expected:
                    raise ValueError("Reused tool_call_id")
                expected[key] = tool
        elif row.call_key.startswith("control:"):
            controls.append(row)
    if len({r.account for r in proof.transcripts}) != len(proof.transcripts):
        raise ValueError("Duplicate worker transcript")
    transcripts = {r.account: r for r in proof.transcripts}
    successful_searches = {}
    for row in proof.calls:
        if row.kind != "tool" or row in controls:
            continue
        _, task = account_task(payload, row.account)
        request = expected.get(row.call_key)
        if request:
            allowed = {
                "rag": {"search_documents", "read_context", "submit_rag_result"},
                "sql": {"database_schema", "query_database", "read_context"},
            }
            if (
                request["name"] not in allowed.get(task.worker, set())
                or row.account not in transcripts
            ):
                raise ValueError("Native tool outside worker/checkpoint authority")
            if row.tool_name != request["name"] or row.fingerprint != digest(
                {"name": request["name"], "arguments": request["args"]}
            ):
                raise ValueError("Native tool response rebound")
        else:
            arguments = bootstrap_arguments(payload, row, task)
            if row.fingerprint != digest({"name": row.tool_name, "arguments": arguments}):
                raise ValueError("Trusted bootstrap fingerprint differs")
        if row.tool_name == "search_documents":
            body = unpack(row)
            if body.get("error") and set(body) != {"error"}:
                raise ValueError("Search refusal contains a contradictory success payload")
            code = (body.get("error") or {}).get("code")
            before_execution = code == "RAG_ATTEMPTS_EXHAUSTED"
            if code == "INPUT_INVALID":
                try:
                    SearchArguments.model_validate(request["args"])
                except ValueError:
                    before_execution = True
            # Known server failures still consume an attempt. Only proven local rejections
            # may be excluded; an error string cannot manufacture more search capacity.
            if not before_execution:
                successful_searches[row.account] = successful_searches.get(row.account, 0) + 1
    if any(n > 2 for n in successful_searches.values()):
        raise ValueError("Actual search quota exceeded")
    if any(key not in calls or calls[key].kind != "tool" for key in expected):
        raise ValueError("Missing native result")
    for account, transcript in transcripts.items():
        account_task(payload, account)
        if transcript.thread_id != proof.run_id:
            raise ValueError("Wrong checkpoint thread")
        pending, seen = {}, set()
        for message in transcript.messages:
            if set(message) != {"type", "data"}:
                raise ValueError("Invalid checkpoint message")
            if message["type"] == "ai" and not any(
                r.kind == "model" and r.account == account and r.payload == message
                for r in proof.calls
            ):
                raise ValueError("Checkpoint assistant differs from Journal")
            if message["type"] in {"ai", "human"} and pending:
                raise ValueError("Unsettled native tool batch")
            if message["type"] == "ai":
                for tool in message["data"].get("tool_calls", []):
                    if tool["id"] in seen:
                        raise ValueError("Duplicate checkpoint tool ID")
                    seen.add(tool["id"])
                    pending[tool["id"]] = tool["name"]
            if message["type"] == "tool":
                d = message["data"]
                if pending.pop(d["tool_call_id"], None) != d.get("name"):
                    raise ValueError("Tool result before model or with wrong ID")
                row = calls.get("tool:" + account + ":" + d["tool_call_id"])
                if (
                    not row
                    or row.tool_name != d.get("name")
                    or unpack(row) != json.loads(d["content"])
                ):
                    raise ValueError("Checkpoint tool differs from Journal")
        if pending:
            raise ValueError("Checkpoint has unsettled tool calls")
    used = set()
    for row in controls:
        version, task = account_task(payload, row.account)
        if (
            task.worker != "rag"
            or row.account in used
            or row.call_key != "control:" + row.account + ":rag-correction"
            or row.tool_name != "rag_completion_correction"
        ):
            raise ValueError("Invalid/duplicate host control identity")
        used.add(row.account)
        notice = Notice.model_validate(unpack(row))
        if row.fingerprint != digest(notice.model_dump()):
            raise ValueError("Host control fingerprint differs")
        transcript = transcripts.get(row.account)
        if transcript is None:
            raise ValueError("Missing trusted checkpoint source")
        matching = []
        for index, message in enumerate(transcript.messages):
            if message["type"] == "human" and message["data"].get("name") == "rag_completion_gate":
                content = json.loads(message["data"]["content"])
                if (
                    set(content) != {"HOST_COMPLETION_CORRECTION", "required"}
                    or content["HOST_COMPLETION_CORRECTION"] != notice.model_dump()
                ):
                    raise ValueError("Host checkpoint notice differs")
                matching.append(index)
        if len(matching) != 1:
            raise ValueError("Missing/duplicate host notice")
        index = matching[0]
        prefix = transcript.messages[:index]
        if not prefix or digest(prefix) != notice.trigger:
            raise ValueError("Host trigger is not the original closed transcript")
        last = prefix[-1]
        if notice.reason == "COMPLETION_REQUIRED":
            if last["type"] != "ai" or last["data"].get("tool_calls"):
                raise ValueError("Plain-final correction trigger differs")
        elif (
            last["type"] != "tool"
            or json.loads(last["data"]["content"]).get("error", {}).get("code") != notice.reason
        ):
            raise ValueError("Correction has no matching tool refusal")
        hooks = [
            i
            for i, e in enumerate(proof.events)
            if (
                e.payload.get("node"),
                e.payload.get("status"),
                e.payload.get("task_id"),
                e.payload.get("plan_version"),
            )
            == ("rag_stop_hook", "correction", task.task_id, version)
        ]
        if len(hooks) != 1 or proof.events[hooks[0]].payload.get("error_code") != notice.reason:
            raise ValueError("Missing/duplicate host trace")
        if notice.reason != "COMPLETION_REQUIRED":
            preceding = [
                i
                for i, e in enumerate(proof.events)
                if e.payload.get("node") == "tool"
                and e.payload.get("tool_call_id") == last["data"]["tool_call_id"]
                and e.payload.get("error_code") == notice.reason
            ]
            if len(preceding) != 1 or preceding[0] >= hooks[0]:
                raise ValueError("Correction precedes tool refusal")
        if notice.reason == "RAG_ATTEMPTS_EXHAUSTED":
            earlier = [
                m
                for m in prefix[:-1]
                if m["type"] == "tool"
                and m["data"].get("name") == "search_documents"
                and not json.loads(m["data"]["content"]).get("error")
            ]
            if len(earlier) != 2:
                raise ValueError("Search rejection did not follow two searches")
    hook_accounts = {
        f"{e.payload.get('plan_version')}:{e.payload.get('task_id')}"
        for e in proof.events
        if e.payload.get("node") == "rag_stop_hook" and e.payload.get("status") == "correction"
    }
    if hook_accounts != used:
        raise ValueError("Host trace/control coverage differs")
    return {
        "valid": True,
        "host_controls": len(controls),
        "native_pairs": len(expected),
        "actual_searches": sum(successful_searches.values()),
    }


def inspect_protocol(record, collector_key, witness_record, witness_key, *, allow_fixture=False):
    try:
        payload = authenticated(record, collector_key)
        proof = Witness.model_validate(authenticated(witness_record, witness_key))
        if proof.source == "synthetic-dev-v1" and (
            not allow_fixture or payload.get("model_mode") == "live"
        ):
            raise ValueError("Synthetic witness cannot attest Live")
        return _verify(payload, proof)
    except (ValueError, KeyError, TypeError, StopIteration, AttributeError):
        return {"valid": False, "reason": "PROTOCOL_PROVENANCE_INVALID"}
