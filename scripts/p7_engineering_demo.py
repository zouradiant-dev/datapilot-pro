"""Bounded synthetic engineering driver using the existing HTTP/outbox/runtime only.

No paid transport, schema/permission changes, Agent scheduler, or product fallback.
The expected results are read by check(), never used to generate an attestation.
"""

import argparse
import hashlib
import json
import os
import secrets
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/p7/engineering-demo-v1"
FIXTURES = ROOT / "tests/fixtures/demo/engineering-v1"
sys.path.insert(0, str(ROOT / "tests"))
from p7_business_scoring import authenticated, sign_collection  # noqa: E402
from report_recovery_probe import ReportDecisions  # noqa: E402
from reporting_fixtures import validate_environment  # noqa: E402

from datapilot.config import Settings  # noqa: E402
from datapilot.contracts import AgentFailure  # noqa: E402
from datapilot.datasets.contracts import DatasetBinding, DatasetScope  # noqa: E402
from datapilot.ingestion.common import digest  # noqa: E402
from datapilot.persistence.backend import Backend, execute  # noqa: E402
from datapilot.persistence.session import run_async  # noqa: E402
from datapilot.runtime.mcp_client import dataset_session  # noqa: E402
from datapilot.web.client import APIClient  # noqa: E402
from datapilot.web.config import load_policy  # noqa: E402
from datapilot.web.store import WebStore  # noqa: E402
from datapilot.web.worker import execute_one  # noqa: E402


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def verified():
    for name in ("engineering-freeze.json", "harness-freeze.json"):
        freeze = json.loads((OUT / name).read_bytes())
        for p, sha in freeze["files"].items():
            assert hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha, p
    assert not (OUT / "STOP.json").exists(), "No new dispatch after STOP"


def settings():
    values = json.loads((OUT / "private/environment.json").read_bytes())
    assert values["DATAPILOT_ADMIN_DATABASE_URL"].endswith(
        "/datapilot_test_engineering_demo_v1_20261031"
    )
    base = validate_environment(values)
    os.environ.update(values)
    os.environ.update(DATAPILOT_LLM_MODE="fake", DATAPILOT_API_KEY="", DATAPILOT_RUN_LIVE_TESTS="0")
    path = OUT / "private/captured-settings.json"
    if path.exists():
        base = Settings(
            _env_file=None,
            llm_mode="fake",
            api_key=None,
            **json.loads(path.read_bytes()),
            **{
                r + "_database_url": values["DATAPILOT_" + r.upper() + "_DATABASE_URL"]
                for r in ("reader", "upload_reader", "runtime", "rag_reader")
            },
        )
    return values, base


def client():
    return APIClient(OUT / "private/host.json")


def serve():
    import uvicorn

    from datapilot.web.app import create_app

    verified()
    _, cfg = settings()
    path = OUT / "private/captured-settings.json"
    if not path.exists():
        write_new(
            path,
            cfg.model_dump(
                mode="json",
                exclude={
                    "api_key",
                    "llm_mode",
                    "reader_database_url",
                    "upload_reader_database_url",
                    "runtime_database_url",
                    "rag_reader_database_url",
                },
            ),
        )
    uvicorn.run(
        create_app(policy=load_policy(OUT / "private/host.json"), settings=cfg, dispatch=False),
        host="127.0.0.1",
        port=8029,
        access_log=False,
        log_level="warning",
    )


def plan():
    return json.loads((FIXTURES / "plan.json").read_bytes())


def selection(case, binding):
    result = {"dataset_id": binding["dataset_id"], "dataset_version": binding["version"]}
    if case["metrics"]:
        result.update(
            metric_id="paid_invoice_revenue", metric_version=1, window=plan()["date_window"]
        )
    if case["documents"]:
        result.update(
            corpus_ids=[binding["corpus_id"]],
            document_purpose="facts" if case.get("required_facts") else "summary",
            required_facts=case.get("required_facts", []),
        )
    return result


def prepare():
    verified()
    _, cfg = settings()
    c = client()
    try:
        preview = c.post(
            "/uploads", files={"file": ("invoices.csv", (FIXTURES / "invoices.csv").read_bytes())}
        )
        id_ = preview["upload_id"]
        conf = c.post(
            f"/uploads/{id_}/confirm",
            {"proposal_sha256": preview["proposal_sha256"], "reviewed": True},
        )
        ds = c.post(
            f"/uploads/{id_}/import",
            {
                "confirmation_sha256": conf["confirmation"]["confirmation_sha256"],
                "name": "engineering-demo-june",
            },
        )
        schema = c.get(f"/datasets/{ds['dataset_id']}/versions/{ds['version']}")["schema"]
        sem = c.post(
            "/semantics/confirm",
            {
                "reviewed": True,
                "draft": {
                    "dataset_id": ds["dataset_id"],
                    "dataset_version": ds["version"],
                    "entities": [
                        {
                            "entity": "invoices",
                            "table_id": schema["tables"][0]["table_id"],
                            "fields": {
                                "record_id": "invoice_id",
                                "amount": "amount_cents",
                                "invoice_date": "invoice_date",
                                "payment_status": "payment_status",
                                "currency": "currency",
                            },
                            "grain": ["invoice_id"],
                            "amount_storage": "minor",
                            "coverage_start": "2026-06-01",
                            "coverage_end_exclusive": "2026-08-01",
                        }
                    ],
                },
            },
        )
        metric = c.post(
            "/metrics/confirm",
            {
                "reviewed": True,
                "draft": {
                    "dataset_id": ds["dataset_id"],
                    "dataset_version": ds["version"],
                    "semantic_version": sem["semantic_version"],
                    "metric_id": "paid_invoice_revenue",
                },
            },
        )
        doc = c.post(
            f"/datasets/{ds['dataset_id']}/versions/{ds['version']}/documents",
            files={"file": ("billing-guide.md", (FIXTURES / "billing-guide.md").read_bytes())},
            data={"reviewed": "true"},
        )
        assert doc["embedding_fixture"] is False
        binding = {
            "dataset_id": ds["dataset_id"],
            "version": ds["version"],
            "schema": schema,
            "semantic": sem,
            "metric": metric,
            **doc,
        }
        write_new(OUT / "binding.json", binding)

        async def gold_query():
            scope = DatasetScope(
                bindings=[DatasetBinding(dataset_id=ds["dataset_id"], version=ds["version"])]
            )
            async with dataset_session(cfg, scope) as tools:
                physical = (await tools.schema(ds["dataset_id"])).tables[0].physical_name
                sql = (
                    f'SELECT SUM(amount_cents)/100::numeric AS revenue FROM uploads."{physical}" '
                    "WHERE payment_status='paid' AND currency='CNY' "
                    "AND invoice_date >= DATE '2026-06-01' AND invoice_date < DATE '2026-07-01'"
                )
                result = await tools.execute(ds["dataset_id"], sql)
                assert Decimal(str(result.result.rows[0][0])) == Decimal("1432.25")
                return {
                    "sql": sql,
                    "result": result.model_dump(mode="json"),
                    "independent_gold": "1432.25 CNY",
                }

        write_new(OUT / "gold-check.json", run_async(gold_query()))
        (OUT / "private/collector-key.bin").write_bytes(secrets.token_bytes(32))
        for case in plan()["cases"]:
            if case["id"] != "unknown":
                create_candidate(c, case, binding)
        print(json.dumps({"prepared": 4, "paid_calls": 0, "numeric_gold": "1432.25 CNY"}))
    finally:
        c.close()


def create_candidate(c, case, binding):
    cid = c.post("/conversations", {})["conversation_id"]
    msg = c.post(
        f"/conversations/{cid}/messages",
        {"text": case["question"], "selection": selection(case, binding)},
    )
    assert msg["text"] == case["question"] and not msg["run_id"]
    write_new(
        OUT / "private" / ("candidate-" + case["id"] + ".json"),
        {"conversation_id": cid, "message": msg},
    )


def pending(c, kind):
    old = json.loads((OUT / "private" / ("candidate-" + kind + ".json")).read_bytes())
    messages = c.get(f"/conversations/{old['conversation_id']}/messages")["messages"]
    msg = next(m for m in messages if m["message_id"] == old["message"]["message_id"])
    return old["conversation_id"], msg


def confirm(c, kind):
    cid, msg = pending(c, kind)
    assert msg["draft"]["request"] is not None, "Use original clarification; never force a scope"
    decision = {"confirmed": True}
    if (g := msg.get("goal_contract")) is not None:
        case = next(x for x in plan()["cases"] if x["id"] == kind)
        binding = json.loads((OUT / "binding.json").read_bytes())
        # Engineering contract review checks identity/input only, never expected report status.
        assert (
            g["original_question"] == case["question"] and g["can_confirm"] and not g["unresolved"]
        )
        assert all(s["corpus_id"] == binding["corpus_id"] for s in g["sources"])
        assert g["review"]["request"]["documents"]["question"] == case["question"]
        decision.update(
            expected_version=g["version"],
            expected_contract_sha256=g["contract_sha256"],
            reviewed_contract=True,
            covers_original_goal=True,
            prerequisites_resolved=True,
        )
    return c.post(
        f"/conversations/{cid}/messages/{msg['message_id']}/launch",
        decision,
        key="demo-launch-" + kind + "-v1",
    )["run_id"]


class LostResponse:
    async def respond(self, *args):
        with (OUT / "private/unknown-attempts.jsonl").open("a", encoding="utf-8") as stream:
            stream.write('{"kind":"synthetic_model_attempt","paid":false}\n')
        raise AgentFailure("MODEL_RATE_LIMIT", "Synthetic unknown outcome", retryable=True)


def worker(kind, label):
    verified()
    values, cfg = settings()
    c = client()
    store = WebStore(values["DATAPILOT_WEB_DATABASE_URL"], load_policy(OUT / "private/host.json"))
    store.settings_provider = lambda: cfg
    try:
        _, msg = pending(c, kind)
        id_ = msg["run_id"]
        assert id_, "No confirmed Web Run"
        row = store.run(id_)
        assert row["processed_seq"] < row["command_seq"], "No pending known command; no replay"
        goal = row["payload"]["report_scope"].get("document_goal")
        transport = (
            LostResponse()
            if kind == "unknown"
            else ReportDecisions(goal["question"] if goal else "")
        )
        worked = run_async(execute_one(cfg, store, id_, transport=transport))
        view = c.get("/tasks/" + id_)
        result = {"run_id": id_, "worked": worked, "view": view}
        if view["report_available"]:
            result["report"] = c.get("/tasks/" + id_ + "/report")
        write_new(OUT / "private" / (label + ".json"), result)
        if view["business_completion"]:
            published = result.get("report", {})
            for fact in published.get("facts", []):
                assert Decimal(fact["value"]["value"]) == Decimal("1432.25")
                assert fact["value"]["unit"] == "CNY" and fact["verification_sha256"]
            if kind == "insufficient":
                assert view["business_completion"]["status"] != "completed", "False Completion"
            if view["business_completion"]["status"] == "completed" and goal:
                assert published.get("citations"), "Completed without required source"
        print(
            json.dumps(
                {"case": kind, "run_id": id_, "status": view["status"], "error": view["error"]}
            )
        )
        return result
    finally:
        c.close()
        store.close()


def run_http(kind):
    assert kind != "rag", "RAG scene is reserved for actual browser confirmation/approval"
    verified()
    c = client()
    try:
        write_new(OUT / ("issued-" + kind + ".json"), {"case": kind, "no_automatic_repeat": True})
        if kind == "unknown":
            case = next(x for x in plan()["cases"] if x["id"] == kind)
            create_candidate(c, case, json.loads((OUT / "binding.json").read_bytes()))
        id_ = confirm(c, kind)
        initial = worker(kind, kind + "-init")
        assert (
            initial["view"]["status"] == "awaiting_review"
            and initial["view"]["usage"]["calls"] == 0
        )
        c.post(
            "/tasks/" + id_ + "/approve", {"confirmed": True}, key="demo-approve-" + kind + "-v1"
        )
        worker(kind, kind + "-executed")
    finally:
        c.close()


def snapshot(label):
    values, cfg = settings()
    c = client()
    store = WebStore(values["DATAPILOT_WEB_DATABASE_URL"], load_policy(OUT / "private/host.json"))
    rows = {}
    try:
        for case in plan()["cases"]:
            cid, msg = pending(c, case["id"])
            id_ = msg["run_id"]
            row = store.run(id_)
            view = c.get("/tasks/" + id_)
            backend = Backend(cfg.runtime_database_url.get_secret_value(), id_, store.policy.owner)
            try:
                with backend.transaction() as conn:
                    manifest = backend.authorize(conn)["manifest"]
                    calls = [
                        dict(x)
                        for x in execute(
                            conn, "SELECT * FROM execution.calls WHERE run_id=:r", r=id_
                        ).mappings()
                    ]
                    ledger = execute(
                        conn, "SELECT payload FROM execution.ledger WHERE run_id=:r", r=id_
                    ).scalar_one()
                    artifacts = [
                        dict(x)
                        for x in execute(
                            conn,
                            "SELECT artifact_id,payload FROM execution.artifacts WHERE run_id=:r",
                            r=id_,
                        ).mappings()
                    ]
                from datapilot.cli import json_default

                calls = json.loads(json.dumps(calls, default=json_default))
                calls.sort(key=digest)
                assert all(a["artifact_id"] == digest(a["payload"]) for a in artifacts)
            finally:
                backend.close()
            item = {
                "message": msg,
                "payload": row["payload"],
                "view": view,
                "manifest": manifest,
                "calls": calls,
                "ledger": ledger,
                "artifact_ids": sorted(a["artifact_id"] for a in artifacts),
            }
            if view["report_available"]:
                item["report"] = c.get("/tasks/" + id_ + "/report")
            rows[case["id"]] = item
        write_new(
            OUT / "private" / ("snapshot-" + label + ".json"),
            sign_collection(rows, (OUT / "private/collector-key.bin").read_bytes()),
        )
        print(json.dumps({k: r["view"]["status"] for k, r in rows.items()}))
    finally:
        c.close()
        store.close()


def check(label):
    rows = authenticated(
        json.loads((OUT / "private" / ("snapshot-" + label + ".json")).read_bytes()),
        (OUT / "private/collector-key.bin").read_bytes(),
    )
    results = {}
    for case in plan()["cases"]:
        row = rows[case["id"]]
        view = row["view"]
        if case["id"] == "unknown":
            assert view["error"]["code"] == "RECOVERY_UNCERTAIN"
            assert any(c["status"] in ("issued", "uncertain") for c in row["calls"])
        else:
            expected = case["expected_status"]
            assert view["business_completion"]["status"] in (
                [expected] if isinstance(expected, str) else expected
            ), case["id"]
            report = row["report"]
            if case["metrics"]:
                fact = report["facts"][0]
                assert (
                    Decimal(fact["value"]["value"]) == Decimal("1432.25")
                    and fact["value"]["unit"] == "CNY"
                )
                assert (
                    fact["evidence_id"] and fact["verification_id"] and fact["verification_sha256"]
                )
            if case["documents"] and case["id"] != "insufficient":
                assert report["citations"] and row["payload"]["goal_confirmation"]
                source_sha = hashlib.sha256(
                    (FIXTURES / "billing-guide.md").read_bytes()
                ).hexdigest()
                assert all(
                    c["citation"]["source_sha256"] == source_sha for c in report["citations"]
                )
        results[case["id"]] = {
            "run_id": view["run_id"],
            "status": view["status"],
            "business_completion": view["business_completion"],
            "error": view["error"],
            "usage": view["usage"],
            "report_sha256": digest(row["report"]) if row.get("report") else None,
            "ledger_sha256": digest(row["ledger"]),
            "calls_sha256": digest(row["calls"]),
            "manifest_sha256": digest(row["manifest"]),
            "artifact_ids": row["artifact_ids"],
        }
    write_new(OUT / ("checks-" + label + ".json"), results)
    print(json.dumps({k: v["status"] for k, v in results.items()}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("serve", "prepare", "run-http", "worker", "snapshot", "check")
    )
    parser.add_argument("--case", choices=("sql", "rag", "combined", "insufficient", "unknown"))
    parser.add_argument("--label")
    args = parser.parse_args()
    try:
        if args.action == "run-http":
            run_http(args.case)
        elif args.action == "worker":
            worker(args.case, args.label)
        elif args.action in ("snapshot", "check"):
            globals()[args.action](args.label)
        else:
            globals()[args.action]()
    except Exception as exc:
        # Preserve failure, no hotfix/retry/new run; external unknown is an expected last scene.
        if not (OUT / "STOP.json").exists():
            write_new(
                OUT / "STOP.json",
                {
                    "action": args.action,
                    "case": args.case,
                    "error_type": type(exc).__name__,
                    "no_new_dispatch": True,
                },
            )
        raise


if __name__ == "__main__":
    main()
