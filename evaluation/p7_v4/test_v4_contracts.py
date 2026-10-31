"""Independent synthetic protocol data, never a Holdout response or model experiment."""

import copy
import json
import os
import sys
from pathlib import Path

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_to_dict,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT / "evaluation/p7_v3"))
sys.path.insert(0, str(ROOT / "scripts"))

from p7_business_scoring import sign_collection  # noqa: E402
from v3_score import call_integrity  # noqa: E402

from datapilot.ingestion.common import digest  # noqa: E402

KEY, WKEY = b"synthetic-collector-key-32-bytes!!", b"synthetic-journal-key-32-bytes!!!!"


def fixture(*, correction=True, third_refused=True):
    run, account = "dev-orchid-run", "1:records"
    messages = [
        SystemMessage(content="Bounded synthetic retrieval worker."),
        HumanMessage(content="Find public orchid support rules."),
    ]
    calls, events = [], []

    def event(node, status, **extra):
        p = {
            "run_id": run,
            "node": node,
            "status": status,
            "plan_version": 1,
            "task_id": "records",
            "sequence": len(events) + 1,
            **extra,
        }
        events.append({"event_id": len(events) + 101, "run_id": run, "payload": p})

    def invoke(index, *, denied=False, name="search_documents"):
        tool_id = "dev_call_" + str(index)
        args = {"query": "orchid rule " + str(index)}
        msg = AIMessage(content="", tool_calls=[{"id": tool_id, "name": name, "args": args}])
        fingerprint = digest({"dev_model_input": index})
        body = messages_to_dict([msg])[0]
        calls.append(
            {
                "run_id": run,
                "call_key": "model:" + account + ":" + fingerprint,
                "fingerprint": fingerprint,
                "kind": "model",
                "account": account,
                "status": "complete",
                "tool_name": None,
                "ticket": "dev-ticket-" + str(index),
                "payload": body,
                "payload_hash": digest(body),
                "elapsed_ms": 1.0,
                "usage": {},
            }
        )
        messages.append(msg)
        result = (
            {
                "error": {
                    "code": "RAG_ATTEMPTS_EXHAUSTED",
                    "message": "No third search",
                    "retryable": False,
                }
            }
            if denied
            else {"document_count": 0, "documents": []}
        )
        saved = {"ordered_json": json.dumps(result, ensure_ascii=False)}
        calls.append(
            {
                "run_id": run,
                "call_key": "tool:" + account + ":" + tool_id,
                "fingerprint": digest({"name": name, "arguments": args}),
                "kind": "tool",
                "account": account,
                "status": "complete",
                "tool_name": name,
                "ticket": None,
                "payload": saved,
                "payload_hash": digest(saved),
                "elapsed_ms": 1.0,
                "usage": None,
            }
        )
        messages.append(ToolMessage(content=json.dumps(result), tool_call_id=tool_id, name=name))
        event(
            "tool",
            "failed" if denied else "succeeded",
            tool_name=name,
            tool_call_id=tool_id,
            error_code="RAG_ATTEMPTS_EXHAUSTED" if denied else None,
        )

    invoke(1)
    invoke(2)
    if correction:
        invoke(3, denied=third_refused)
        notice = {
            "protocol": "rag-submit-v1",
            "reason": "RAG_ATTEMPTS_EXHAUSTED",
            "trigger": digest(messages_to_dict(messages)),
            "attempt": 1,
        }
        saved = {"ordered_json": json.dumps(notice)}
        calls.append(
            {
                "run_id": run,
                "call_key": "control:" + account + ":rag-correction",
                "fingerprint": digest(notice),
                "kind": "tool",
                "account": account,
                "status": "complete",
                "tool_name": "rag_completion_correction",
                "ticket": None,
                "payload": saved,
                "payload_hash": digest(saved),
                "elapsed_ms": None,
                "usage": None,
            }
        )
        messages.append(
            HumanMessage(
                name="rag_completion_gate",
                content=json.dumps(
                    {
                        "HOST_COMPLETION_CORRECTION": notice,
                        "required": "Submit bounded evidence only.",
                    }
                ),
            )
        )
        event("rag_stop_hook", "correction", error_code="RAG_ATTEMPTS_EXHAUSTED")
    plan = {
        "tasks": [
            {
                "task_id": "records",
                "worker": "rag",
                "instruction": "Find public orchid rules",
                "dependencies": [],
            }
        ],
        "unsupported": False,
    }
    manifest = {"owner": "synthetic-owner"}
    projection = [
        {k: v for k, v in c.items() if k not in {"run_id", "fingerprint", "ticket"}} for c in calls
    ]
    payload = {
        "case_id": "synthetic-orchid-protocol",
        "run_id": run,
        "manifest": manifest,
        "manifest_sha256": digest(manifest),
        "model_mode": "fake_fixture",
        "calls": projection,
        "events": [e["payload"] for e in events],
        "snapshot": {"state": {"plan_history": {"1": plan}}},
    }
    proof = {
        "schema_version": "p7-v4-journal-witness-1",
        "source": "synthetic-dev-v1",
        "case_id": payload["case_id"],
        "run_id": run,
        "owner": manifest["owner"],
        "manifest_sha256": digest(manifest),
        "collection_sha256": digest(payload),
        "calls": calls,
        "events": events,
        "transcripts": [
            {
                "account": account,
                "thread_id": run,
                "checkpoint_id": "dev-checkpoint",
                "checkpoint_ns": "dev-worker:orchid|loop:bounded",
                "messages": messages_to_dict(messages),
            }
        ],
    }
    return payload, proof


def check(payload, proof):
    if os.environ.get("DATAPILOT_SCORER_RED_BASELINE") == "v3":
        return call_integrity(payload)
    from v4_protocol import inspect_protocol

    return inspect_protocol(
        sign_collection(payload, KEY), KEY, sign_collection(proof, WKEY), WKEY, allow_fixture=True
    )["valid"]


def sync(payload, proof):
    # A trusted fixture signer can attest mutations: validation must still reject bad semantics.
    proof["collection_sha256"] = digest(payload)


def test_legal_native_call_result_pair():
    assert check(*fixture(correction=False))


def test_legal_host_stop_hook_correction():
    assert check(*fixture())


def test_two_searches_and_third_denied_are_not_three_executions():
    assert check(*fixture())


@pytest.mark.parametrize(
    "mutation",
    [
        "orphan",
        "wrong_run",
        "wrong_task",
        "wrong_worker",
        "hash",
        "duplicate_control",
        "missing_control",
        "missing_trace",
        "reversed_events",
        "wrong_trigger",
        "wrong_checkpoint",
        "wrong_reason",
        "reused_tool_id",
        "missing_result",
        "rename_result_control",
        "wrong_fingerprint",
        "missing_transcript",
        "unknown_tool",
        "invalid_dto",
        "boolean_attempt",
    ],
)
def test_control_and_native_adversarial_mutations_fail_closed(mutation):
    p, w = fixture()
    c = w["calls"][-1]
    if mutation == "orphan":
        orphan = copy.deepcopy(w["calls"][1])
        orphan["call_key"] += "orphan"
        w["calls"].append(orphan)
        p["calls"].append(
            {k: v for k, v in orphan.items() if k not in {"run_id", "fingerprint", "ticket"}}
        )
    elif mutation == "wrong_run":
        w["calls"][0]["run_id"] = "wrong-run"
    elif mutation == "wrong_task":
        c["account"] = "1:unknown"
    elif mutation == "wrong_worker":
        p["snapshot"]["state"]["plan_history"]["1"]["tasks"][0]["worker"] = "sql"
    elif mutation == "hash":
        c["payload_hash"] = "0" * 64
    elif mutation == "duplicate_control":
        w["calls"].append(copy.deepcopy(c))
    elif mutation == "missing_control":
        w["calls"].pop()
        p["calls"].pop()
    elif mutation == "missing_trace":
        w["events"].pop()
        p["events"].pop()
    elif mutation == "reversed_events":
        w["events"] = list(reversed(w["events"]))
        p["events"] = [e["payload"] for e in w["events"]]
    elif mutation == "wrong_trigger":
        body = json.loads(c["payload"]["ordered_json"])
        body["trigger"] = "0" * 64
        c["payload"] = {"ordered_json": json.dumps(body)}
        c["payload_hash"] = digest(c["payload"])
    elif mutation == "wrong_checkpoint":
        w["transcripts"][0]["thread_id"] = "foreign-run"
    elif mutation == "wrong_reason":
        w["events"][-1]["payload"]["error_code"] = "INPUT_INVALID"
    elif mutation == "reused_tool_id":
        message = w["calls"][2]["payload"]["data"]
        message["tool_calls"][0]["id"] = "dev_call_1"
        w["calls"][2]["payload_hash"] = digest(w["calls"][2]["payload"])
    elif mutation == "missing_result":
        w["calls"].pop(1)
        p["calls"].pop(1)
    elif mutation == "rename_result_control":
        w["calls"][1]["tool_name"] = "rag_completion_correction"
    elif mutation == "wrong_fingerprint":
        c["fingerprint"] = "0" * 64
    elif mutation == "missing_transcript":
        w["transcripts"] = []
    elif mutation == "unknown_tool":
        w["calls"][1]["tool_name"] = "shell"
    elif mutation == "invalid_dto":
        w["trusted"] = True
    elif mutation == "boolean_attempt":
        notice = json.loads(c["payload"]["ordered_json"])
        notice["attempt"] = True
        c["payload"] = {"ordered_json": json.dumps(notice)}
        c["payload_hash"] = digest(c["payload"])
    # Reconcile the public projection; this is not just an HMAC mismatch test.
    for row in p["calls"]:
        match = next((x for x in w["calls"] if x["call_key"] == row["call_key"]), None)
        if match:
            row.update({k: v for k, v in match.items() if k in row})
    sync(p, w)
    assert not check(p, w)


def test_third_actual_search_is_rejected():
    assert not check(*fixture(third_refused=False))


def test_no_journal_source_is_rejected():
    from v4_protocol import inspect_protocol

    p, _ = fixture()
    assert not inspect_protocol(sign_collection(p, KEY), KEY, {}, WKEY)["valid"]


def test_synthetic_witness_cannot_attest_live():
    from v4_protocol import inspect_protocol

    p, w = fixture()
    p["model_mode"] = "live"
    sync(p, w)
    assert not inspect_protocol(
        sign_collection(p, KEY), KEY, sign_collection(w, WKEY), WKEY, allow_fixture=True
    )["valid"]


def test_tampered_signed_collection_and_proof_are_rejected():
    from v4_protocol import inspect_protocol

    p, w = fixture()
    r, q = sign_collection(p, KEY), sign_collection(w, WKEY)
    r["signature"] = "0" * 64
    assert not inspect_protocol(r, KEY, q, WKEY, allow_fixture=True)["valid"]
    r = sign_collection(p, KEY)
    q["signature"] = "0" * 64
    assert not inspect_protocol(r, KEY, q, WKEY, allow_fixture=True)["valid"]


def publish(p, w):
    p["calls"] = [
        {k: v for k, v in c.items() if k not in {"run_id", "fingerprint", "ticket"}}
        for c in w["calls"]
    ]
    p["events"] = [e["payload"] for e in w["events"]]
    p["manifest_sha256"] = digest(p["manifest"])
    w["manifest_sha256"] = p["manifest_sha256"]
    sync(p, w)


def test_plain_final_host_correction_is_separately_supported():
    p, w = fixture(correction=False)
    transcript = w["transcripts"][0]["messages"]
    message = messages_to_dict(
        [AIMessage(content="Cannot produce a free-form final without submission.")]
    )[0]
    fp = digest({"dev_final": 8})
    row = copy.deepcopy(w["calls"][0])
    row.update(
        call_key="model:1:records:" + fp,
        fingerprint=fp,
        payload=message,
        payload_hash=digest(message),
    )
    w["calls"].append(row)
    transcript.append(message)
    notice = {
        "protocol": "rag-submit-v1",
        "reason": "COMPLETION_REQUIRED",
        "trigger": digest(transcript),
        "attempt": 1,
    }
    body = {"ordered_json": json.dumps(notice)}
    c = copy.deepcopy(w["calls"][1])
    c.update(
        call_key="control:1:records:rag-correction",
        fingerprint=digest(notice),
        tool_name="rag_completion_correction",
        payload=body,
        payload_hash=digest(body),
    )
    w["calls"].append(c)
    transcript.extend(
        messages_to_dict(
            [
                HumanMessage(
                    name="rag_completion_gate",
                    content=json.dumps(
                        {"HOST_COMPLETION_CORRECTION": notice, "required": "Submit once"}
                    ),
                )
            ]
        )
    )
    e = copy.deepcopy(w["events"][-1])
    e["event_id"] += 1
    e["payload"].update(
        node="rag_stop_hook", status="correction", sequence=3, error_code="COMPLETION_REQUIRED"
    )
    w["events"].append(e)
    publish(p, w)
    assert check(p, w)


@pytest.mark.parametrize(
    "tool,worker,task_id,call_id,args",
    [
        (
            "p3_metric_execution",
            "sql",
            "count_metric",
            "metric",
            {"request": {"goal_id": "count_metric"}},
        ),
        (
            "verified_report_projection",
            "report",
            "write_summary",
            "report",
            {"inputs": [], "source_statuses": {"records": "unavailable"}},
        ),
    ],
)
def test_trusted_p3_report_bootstrap_is_not_a_name_only_exemption(
    tool, worker, task_id, call_id, args
):
    p, w = fixture(correction=False)
    plan = p["snapshot"]["state"]["plan_history"]["1"]
    plan["tasks"].append(
        {
            "task_id": task_id,
            "worker": worker,
            "instruction": "Deterministic host operation",
            "dependencies": ["records"] if worker == "report" else [],
        }
    )
    p["manifest"]["cross_source_report"] = {"scope": {"metrics": [{"goal_id": "count_metric"}]}}
    p["snapshot"]["state"].update(
        results={"1:records": {"status": "unavailable", "worker": "rag", "evidence_refs": []}},
        verifications={"1:records": {"status": "unavailable"}},
    )
    row = copy.deepcopy(w["calls"][1])
    row.update(
        account="1:" + task_id,
        call_key="tool:1:" + task_id + ":" + call_id,
        tool_name=tool,
        fingerprint=digest({"name": tool, "arguments": args}),
        payload={"ordered_json": "{}"},
    )
    row["payload_hash"] = digest(row["payload"])
    w["calls"].append(row)
    publish(p, w)
    assert check(p, w)
    row["fingerprint"] = "0" * 64
    publish(p, w)
    assert not check(p, w)


def test_host_trace_cannot_precede_its_rejected_tool():
    p, w = fixture()
    w["events"][-2]["payload"], w["events"][-1]["payload"] = (
        w["events"][-1]["payload"],
        w["events"][-2]["payload"],
    )
    for index, e in enumerate(w["events"], 1):
        e["payload"]["sequence"] = index
    publish(p, w)
    assert not check(p, w)


@pytest.mark.parametrize(
    "field", ["schema_version", "source", "run_id", "calls", "events", "transcripts"]
)
def test_missing_required_witness_dto_fields_rejected(field):
    p, w = fixture()
    w.pop(field)
    assert not check(p, w)


def test_original_v3_evaluator_seal_cannot_be_used_as_v4():
    from pydantic import ValidationError
    from v4_score import EvaluatorFreeze

    with pytest.raises(ValidationError):
        EvaluatorFreeze.model_validate({"version": "v3", "live_allowed": False})


def test_wrong_control_event_kind_cannot_replace_a_result():
    p, w = fixture()
    w["calls"][-1]["kind"] = "control"
    publish(p, w)
    assert not check(p, w)


def test_protocol_repair_does_not_promote_missing_business_evidence(monkeypatch):
    import v3_score
    import v4_score

    original_checker = v3_score.call_integrity
    old = {
        "strict_correct": False,
        "dimensions": {
            "protocol": False,
            "citations": False,
            "fact_coverage": False,
            "completion": False,
        },
        "failure_class": "rag_retrieval_failure",
    }
    saved = copy.deepcopy(old)
    monkeypatch.setattr(v3_score, "score", lambda *args: old)
    monkeypatch.setattr(v4_score, "inspect_protocol", lambda *args: {"valid": True})
    revised = v4_score.score(None, None, {}, KEY, {}, {}, WKEY)
    assert revised["dimensions"]["protocol"] is True
    assert revised["strict_correct"] is False
    assert revised["failure_class"] == "rag_retrieval_failure"
    assert old == saved and v3_score.call_integrity is original_checker


@pytest.mark.parametrize("mutation", ["none", "foreign_key", "changed_witness", "changed_manifest"])
def test_sealed_readonly_witness_file_and_key_are_bound(tmp_path, monkeypatch, mutation):
    from types import SimpleNamespace

    import v4_score
    from v3_common import sha

    monkeypatch.setattr(v4_score, "ROOT", tmp_path)
    witness = tmp_path / "witness.json"
    witness.write_text('{"synthetic":"sealed"}\n', encoding="utf-8")
    path = "artifacts/p7/scorer-v4/private/witness-manifest-r2.json"
    manifest = tmp_path / path
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"files": {"dev": sha(witness.read_bytes())}, "signing_key_sha256": sha(WKEY)}),
        encoding="utf-8",
    )
    frozen = SimpleNamespace(
        witness_manifest_path=path, witness_manifest_sha256=sha(manifest.read_bytes())
    )
    key = WKEY
    if mutation == "foreign_key":
        key = b"foreign-collector-signer-is-not-the-host"
    if mutation == "changed_witness":
        witness.write_text("{}", encoding="utf-8")
    if mutation == "changed_manifest":
        manifest.write_text("{}", encoding="utf-8")
    if mutation == "none":
        assert v4_score.bound_witness(frozen, "dev", witness, key) == {"synthetic": "sealed"}
    else:
        with pytest.raises(ValueError):
            v4_score.bound_witness(frozen, "dev", witness, key)


def test_known_failed_third_execution_cannot_escape_the_search_quota():
    p, w = fixture()
    w["calls"].pop()  # This scenario ended on a known failure, without a correction.
    w["events"].pop()
    w["transcripts"][0]["messages"].pop()
    row = w["calls"][-1]
    result = {
        "error": {
            "code": "QUERY_ERROR",
            "message": "Known completed server failure",
            "retryable": False,
        }
    }
    row["payload"] = {"ordered_json": json.dumps(result)}
    row["payload_hash"] = digest(row["payload"])
    w["transcripts"][0]["messages"][-1]["data"]["content"] = json.dumps(result)
    w["events"][-1]["payload"]["error_code"] = "QUERY_ERROR"
    publish(p, w)
    assert not check(p, w)
