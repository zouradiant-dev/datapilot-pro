"""Six original review counterexamples: real PG except the dispatcher poll unit test."""

import asyncio
import json
from contextlib import suppress
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from test_web_postgres import api as _api
from test_web_postgres import import_sample

from datapilot.config import Settings
from datapilot.persistence.backend import Backend, execute
from datapilot.persistence.session import run_async
from datapilot.web.client import APIClient
from datapilot.web.service import ProductService
from datapilot.web.worker import Dispatcher, execute_one

api = _api
pytestmark = pytest.mark.integration


def test_cancel_between_outbox_read_and_runtime_registration(api):
    c, app, settings = api
    request = import_sample(c)
    request["require_review"] = False
    id_ = c.post("/api/v1/tasks", json=request, headers={"Idempotency-Key": uuid4().hex}).json()[
        "run_id"
    ]
    original = ProductService.authorize_run
    cancelled = []

    async def cancel_in_window(service, run_id):
        if not cancelled:
            response = c.post(
                f"/api/v1/tasks/{run_id}/cancel", json={}, headers={"Idempotency-Key": uuid4().hex}
            )
            cancelled.append(response.status_code)
        return await original(service, run_id)

    with patch.object(ProductService, "authorize_run", cancel_in_window):
        run_async(execute_one(settings, app.state.store, id_))
    assert cancelled == [200]
    state = c.get("/api/v1/tasks/" + id_).json()
    assert state["status"] == "cancelled", f"accepted cancellation became {state['status']}"
    assert state["usage"]["calls"] == 0


def test_retry_of_lost_create_ack_uses_same_logical_key(api):
    c, app, _ = api
    body = import_sample(c)
    created, keys = [], []

    def proxy(request):
        keys.append(request.headers["Idempotency-Key"])
        result = c.post(
            "/api/v1/tasks", json=json.loads(request.content), headers={"Idempotency-Key": keys[-1]}
        )
        assert result.status_code == 200
        created.append(result.json()["run_id"])
        if len(created) == 1:
            raise httpx.ReadTimeout("accepted server response lost", request=request)
        return httpx.Response(200, json=result.json())

    ui_client = APIClient.__new__(APIClient)
    ui_client.http = httpx.Client(base_url="http://review", transport=httpx.MockTransport(proxy))
    try:
        with pytest.raises(httpx.ReadTimeout):
            ui_client.post("/tasks", body)
        ui_client.post("/tasks", body)  # Same UI call after connection error.
    finally:
        ui_client.close()
    assert len(set(created)) == 1, "retry created two independently executable runs"


def test_transient_poll_failure_does_not_permanently_stop_dispatch():
    class Store:
        def __init__(self):
            self.polls = 0

        def pending(self):
            self.polls += 1
            if self.polls == 1:
                raise OSError("temporary database disconnect")
            return []

    async def scenario():
        d = Dispatcher(Store(), "unused-test-host.json")
        task = asyncio.create_task(d.run())
        await asyncio.sleep(0)
        terminated = task.done()
        d.stopping = True
        task.cancel()
        with suppress(asyncio.CancelledError, OSError):
            await task
        assert not terminated, "one transient poll error killed the only dispatcher"

    run_async(scenario())


def test_dataset_list_does_not_break_after_101_accepted_versions(api):
    c, app, _ = api
    import_sample(c)
    example = app.state.store.datasets()[0]
    probe = TestClient(app, raise_server_exceptions=False)
    probe.headers.update(c.headers)
    probe.cookies.update(c.cookies)
    try:
        with patch.object(app.state.store, "datasets", return_value=[example] * 101):
            response = probe.get("/api/v1/datasets")
        assert response.status_code == 200, (
            "101 stored records cause the entire dataset list to fail"
        )
    finally:
        probe.close()


def test_revoked_corpus_is_filtered_without_breaking_other_authorized_datasets(api):
    from pathlib import Path

    c, app, _ = api
    first = import_sample(c)["metrics"][0]
    second = import_sample(c)["metrics"][0]
    content = Path("tests/fixtures/reporting/billing.md").read_bytes()
    doc = c.post(
        f"/api/v1/datasets/{first['dataset_id']}/versions/1/documents",
        files={"file": ("billing.md", content)},
        data={"reviewed": "true"},
    )
    assert doc.status_code == 200
    with app.state.store.transaction() as conn:
        conn.execute(
            sa.text(
                "UPDATE execution.web_datasets SET enabled=false WHERE owner=:o AND dataset_id=:d"
            ),
            {"o": app.state.store.policy.owner, "d": first["dataset_id"]},
        )
    assert c.get(f"/api/v1/datasets/{second['dataset_id']}/versions/1").status_code == 200
    result = c.get("/api/v1/corpora")
    assert result.status_code == 200, "one revoked dataset denies the global corpus list"
    assert result.json()["corpora"] == []


def test_worker_rechecks_current_host_policy_instead_of_its_saved_settings(api):
    c, app, original_settings = api
    request = import_sample(c)
    request["require_review"] = False
    id_ = c.post("/api/v1/tasks", json=request, headers={"Idempotency-Key": uuid4().hex}).json()[
        "run_id"
    ]
    frozen = Settings(**app.state.store.run(id_)["payload"]["settings"])
    app.state.service.settings = original_settings.model_copy(update={"max_model_calls": 1})
    assert c.get("/api/v1/tasks/" + id_).status_code == 403  # Current host policy rejects it.
    run_async(
        execute_one(frozen, app.state.store, id_)
    )  # Same settings reconstruction as worker.main.
    backend = Backend(
        original_settings.runtime_database_url.get_secret_value(), id_, app.state.store.policy.owner
    )
    try:
        with backend.engine.connect() as conn:
            calls = execute(
                conn, "SELECT count(*) FROM execution.calls WHERE run_id=:r", r=id_
            ).scalar_one()
        assert calls == 0, "dispatcher executed an operation current API policy rejects"
    finally:
        backend.close()


def test_cancel_is_monotonic_after_worker_restart_and_old_create_replay(api):
    from datapilot.contracts import AgentFailure
    from datapilot.db.management import management_url
    from datapilot.web.store import WebStore

    c, app, settings = api
    body = import_sample(c)
    key = uuid4().hex
    ack = c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": key}).json()
    id_ = ack["run_id"]
    assert (
        c.post(
            f"/api/v1/tasks/{id_}/cancel", json={}, headers={"Idempotency-Key": uuid4().hex}
        ).status_code
        == 200
    )
    restarted = WebStore(management_url("web"), app.state.store.policy)
    restarted.settings_provider = lambda: settings
    try:
        assert run_async(execute_one(settings, restarted, id_))
        assert not run_async(execute_one(settings, restarted, id_))
        with pytest.raises(AgentFailure) as refused:
            restarted.command(uuid4().hex, "approve", {"confirmed": True}, run_id=id_)
        assert refused.value.error.code == "CANCELLED"
        assert restarted.run(id_)["cancel_requested"]
    finally:
        restarted.close()
    assert c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": key}).json() == ack
    state = c.get("/api/v1/tasks/" + id_).json()
    assert state["status"] == "cancelled" and state["usage"]["calls"] == 0


def test_cancel_during_durable_initialization_has_no_execution_gap(api, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import datapilot.web.worker as worker

    c, app, settings = api
    body = import_sample(c)
    body["require_review"] = False
    id_ = c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": uuid4().hex}).json()[
        "run_id"
    ]
    entered, release, acknowledged = (threading.Event() for _ in range(3))
    original = worker.run_durable

    async def controlled(*args, **kwargs):
        if kwargs.get("interrupt_before"):
            entered.set()
            assert await asyncio.to_thread(release.wait, 30)
        else:
            assert await asyncio.to_thread(acknowledged.wait, 30)
        return await original(*args, **kwargs)

    monkeypatch.setattr(worker, "run_durable", controlled)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(run_async, execute_one(settings, app.state.store, id_))
        assert entered.wait(30)
        cancellation = pool.submit(
            c.post, f"/api/v1/tasks/{id_}/cancel", json={}, headers={"Idempotency-Key": uuid4().hex}
        )
        release.set()
        assert cancellation.result(timeout=60).status_code == 200
        acknowledged.set()
        assert future.result(timeout=60)
    state = c.get("/api/v1/tasks/" + id_).json()
    assert state["status"] == "cancelled", state
    assert state["usage"]["calls"] == 0


def test_stable_ui_intent_survives_reconnect_and_explicit_new_intent(api):
    from datapilot.web.client import ClientError, creation_intent

    c, _, _ = api
    body = import_sample(c)
    intent = creation_intent(None, body)
    original_key = intent["key"]
    created = []

    def proxy(request):
        result = c.post(
            "/api/v1/tasks",
            json=json.loads(request.content),
            headers={"Idempotency-Key": request.headers["Idempotency-Key"]},
        )
        assert result.status_code == 200
        created.append(result.json()["run_id"])
        if len(created) == 1:
            raise httpx.ReadTimeout("lost acknowledgement", request=request)
        return httpx.Response(200, json=result.json())

    for attempt in range(2):
        client = APIClient.__new__(APIClient)
        client.http = httpx.Client(base_url="http://test", transport=httpx.MockTransport(proxy))
        try:
            # JSON roundtrip represents Streamlit rerun state; new HTTP client on retry.
            intent = creation_intent(json.loads(json.dumps(intent)), body)
            if attempt == 0:
                with pytest.raises(httpx.ReadTimeout):
                    client.post("/tasks", intent["body"], key=intent["key"])
            else:
                assert (
                    client.post("/tasks", intent["body"], key=intent["key"])["run_id"] == created[0]
                )
                new = creation_intent(None, body)  # Explicit new user intention.
                assert new["key"] != original_key
                client.post("/tasks", new["body"], key=new["key"])
        finally:
            client.close()
    assert created[0] == created[1] != created[2]
    with pytest.raises(ClientError):
        creation_intent(intent, {**body, "question": "different"})


def test_current_host_policy_is_shared_with_a_separate_worker_process(api, tmp_path):
    import os
    import subprocess
    import sys

    c, app, settings = api
    body = import_sample(c)
    id_ = c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": uuid4().hex}).json()[
        "run_id"
    ]
    policy_file = tmp_path / "host.json"
    policy_file.write_text(app.state.store.policy.model_dump_json(), encoding="utf-8")
    app.state.service.settings = settings.model_copy(update={"max_model_calls": 1})
    result = subprocess.run(
        [sys.executable, "-m", "datapilot.web.worker", id_, "--host-file", str(policy_file)],
        env={**os.environ, "DATAPILOT_LLM_MODE": "fake", "DATAPILOT_MAX_MODEL_CALLS": "8"},
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0
    row = app.state.store.run(id_)
    assert row["last_error"]["code"] == "RECOVERY_VERSION"
    assert row["last_error"]["manual_action_required"]
    assert row["command_seq"] == row["processed_seq"]
    backend = Backend(
        settings.runtime_database_url.get_secret_value(), id_, app.state.store.policy.owner
    )
    try:
        with backend.engine.connect() as conn:
            assert (
                execute(
                    conn, "SELECT count(*) FROM execution.runs WHERE run_id=:r", r=id_
                ).scalar_one()
                == 0
            )
    finally:
        backend.close()


def test_database_identity_and_model_policy_changes_fail_closed(api):
    from pydantic import SecretStr
    from sqlalchemy.engine import make_url

    from datapilot.contracts import AgentFailure

    _, app, settings = api
    store = app.state.store
    changes = [
        {"max_model_calls": 1},
        {"model": "different-model"},
        {"base_url": "https://different.invalid"},
        {"llm_mode": "live"},
    ]
    for name in (
        "reader_database_url",
        "upload_reader_database_url",
        "runtime_database_url",
        "rag_reader_database_url",
    ):
        old = make_url(getattr(settings, name).get_secret_value())
        changes.append(
            {
                name: SecretStr(
                    old.set(database="other_database").render_as_string(hide_password=False)
                )
            }
        )
        rotated = settings.model_copy(
            update={
                name: SecretStr(
                    old.set(password="rotated-local-test-secret").render_as_string(
                        hide_password=False
                    )
                )
            }
        )
        assert store.host_settings_hash(rotated) == store.host_settings_hash(settings)
    for change in changes:
        with pytest.raises(AgentFailure) as refused:
            store.check_host_settings(settings.model_copy(update=change))
        assert refused.value.error.code == "RECOVERY_VERSION"


def test_dispatch_process_crash_is_quarantined_and_another_run_can_proceed(
    api, tmp_path, monkeypatch
):
    import subprocess
    import sys
    import time

    c, app, _ = api
    body = import_sample(c)
    ids = [
        c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": uuid4().hex}).json()[
            "run_id"
        ]
        for _ in range(2)
    ]
    policy_file = tmp_path / "host.json"
    policy_file.write_text(app.state.store.policy.model_dump_json(), encoding="utf-8")
    popen = subprocess.Popen
    launches = []

    def launch(command, **kwargs):
        launches.append(command[3])
        kwargs["env"] = {**kwargs["env"], "DATAPILOT_LLM_MODE": "fake"}
        if command[3] == ids[0]:
            return popen([sys.executable, "-c", "raise SystemExit(9)"], **kwargs)
        return popen(command, **kwargs)

    monkeypatch.setattr("datapilot.web.worker.subprocess.Popen", launch)
    dispatcher = Dispatcher(app.state.store, policy_file)
    deadline = time.monotonic() + 90
    try:
        while time.monotonic() < deadline:
            dispatcher.poll()
            rows = [app.state.store.run(id_) for id_ in ids]
            if all(r["command_seq"] == r["processed_seq"] for r in rows):
                break
            time.sleep(0.2)
        assert rows[0]["last_error"]["code"] == "WEB_DISPATCH_FAILED"
        assert rows[0]["last_error"]["manual_action_required"]
        assert rows[1]["status_hint"] == "awaiting_review", rows[1]["last_error"]
        for _ in range(3):
            dispatcher.poll()
        assert launches.count(ids[0]) == launches.count(ids[1]) == 1
        # A fresh dispatcher cannot restart the quarantined command.
        Dispatcher(app.state.store, policy_file).poll()
        assert len(launches) == 2
    finally:
        for child in dispatcher.children.values():
            child.wait(timeout=60)


def test_lost_dispatch_launch_and_busy_retries_are_bounded_in_the_outbox(api):
    c, app, _ = api
    body = import_sample(c)
    id_ = c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": uuid4().hex}).json()[
        "run_id"
    ]
    store = app.state.store
    seq = store.dispatch_start(id_)
    # Restart after an unacknowledged launch does not assume it never executed.
    assert store.dispatch_start(id_) is None
    assert store.run(id_)["last_error"]["manual_action_required"]
    id_ = c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": uuid4().hex}).json()[
        "run_id"
    ]
    for _ in range(3):
        seq = store.dispatch_start(id_)
        assert seq is not None
        store.dispatch_busy(id_, seq)
    assert store.dispatch_start(id_) is None
    assert store.run(id_)["last_error"]["code"] == "WEB_DISPATCH_FAILED"


def test_valid_corpus_survives_unrelated_revocation_and_corrupt_pin_is_rejected(api):
    from pathlib import Path

    from datapilot.ingestion.common import digest

    c, app, _ = api
    sources = [import_sample(c)["metrics"][0] for _ in range(2)]
    corpora = []
    for s in sources:
        r = c.post(
            f"/api/v1/datasets/{s['dataset_id']}/versions/1/documents",
            files={
                "file": ("billing.md", Path("tests/fixtures/reporting/billing.md").read_bytes())
            },
            data={"reviewed": "true"},
        )
        assert r.status_code == 200, r.text
        corpora.append(r.json()["corpus_id"])
    with app.state.store.transaction() as conn:
        conn.execute(
            sa.text(
                "UPDATE execution.web_datasets SET enabled=false WHERE owner=:o AND dataset_id=:d"
            ),
            {"o": app.state.store.policy.owner, "d": sources[0]["dataset_id"]},
        )
    r = c.get("/api/v1/corpora")
    assert r.status_code == 200, r.text
    assert [p["corpus_id"] for p in r.json()["corpora"]] == [corpora[1]]
    # Even a self-consistent JSON hash cannot authorize a pin for the wrong corpus.
    row = app.state.store.corpora()[0]
    corrupt = {**row["payload"], "corpus_id": str(uuid4())}
    with app.state.store.transaction() as conn:
        conn.execute(
            sa.text(
                "UPDATE execution.web_corpora SET payload=CAST(:p AS jsonb),payload_hash=:h "
                "WHERE owner=:o AND corpus_id=:id"
            ),
            {
                "p": json.dumps(corrupt),
                "h": digest(corrupt),
                "o": app.state.store.policy.owner,
                "id": corpora[1],
            },
        )
    assert c.get("/api/v1/corpora").status_code == 403


def test_dataset_pages_at_100_101_and_205_metadata_grants(api):
    from datapilot.datasets.contracts import DatasetSchema

    c, app, _ = api
    import_sample(c)
    schema = DatasetSchema.model_validate(app.state.store.datasets()[0]["schema"])
    # Synthetic Web grant metadata tests the actual PG listing, not 205 business imports.
    for count in range(2, 206):
        app.state.store.grant(schema.model_copy(update={"dataset_id": str(uuid4())}))
        if count in {100, 101, 205}:
            seen, offset = [], 0
            while offset is not None:
                response = c.get(f"/api/v1/datasets?offset={offset}")
                assert response.status_code == 200, response.text
                page = response.json()
                assert len(page["datasets"]) <= 100
                seen.extend(p["schema"]["dataset_id"] for p in page["datasets"])
                offset = page["next_offset"]
            assert len(set(seen)) == len(seen) == count
            assert seen == sorted(seen)
    assert c.get("/api/v1/datasets?offset=300").json()["datasets"] == []
    for query in ("limit=101", "limit=0", "offset=-1"):
        assert c.get("/api/v1/datasets?" + query).status_code == 422


@pytest.mark.parametrize("registered", [False, True])
def test_legacy_web_payload_retains_manifest_checks_or_requires_reauthorization(api, registered):
    from datapilot.ingestion.common import digest

    c, app, settings = api
    body = import_sample(c)
    id_ = c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": uuid4().hex}).json()[
        "run_id"
    ]
    if registered:
        run_async(execute_one(settings, app.state.store, id_))
        assert c.get("/api/v1/tasks/" + id_).json()["status"] == "awaiting_review"
    old = app.state.store.run(id_)["payload"]
    old.pop("host_policy_sha256")
    with app.state.store.transaction() as conn:
        conn.execute(
            sa.text(
                "UPDATE execution.web_runs SET payload=CAST(:p AS jsonb),payload_hash=:h "
                "WHERE run_id=:r"
            ),
            {"p": json.dumps(old), "h": digest(old), "r": id_},
        )
    if registered:
        assert (
            c.post(
                f"/api/v1/tasks/{id_}/approve",
                json={"confirmed": True},
                headers={"Idempotency-Key": uuid4().hex},
            ).status_code
            == 200
        )
    run_async(execute_one(settings, app.state.store, id_))
    view = c.get("/api/v1/tasks/" + id_).json()
    if registered:
        assert view["status"] == "completed", view
    else:
        assert view["status"] == "blocked", view
        assert view["error"]["code"] == "RECOVERY_POLICY_UNBOUND"
        assert view["error"]["manual_action_required"]


def test_upgrade_retry_preserves_legacy_creation_key(api):
    from datapilot.web.contracts import CreateTask

    c, app, _ = api
    body = import_sample(c)
    old = run_async(app.state.service.task_payload(CreateTask.model_validate(body)))
    old.pop("host_policy_sha256")
    key = uuid4().hex
    ack = app.state.store.command(key, "create", old, payload=old)
    result = c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": key})
    assert result.status_code == 200, result.text
    assert result.json() == ack
    assert app.state.store.run(ack["run_id"])["payload"] == old
    assert (
        c.post(
            "/api/v1/tasks",
            json={**body, "question": "different"},
            headers={"Idempotency-Key": key},
        ).status_code
        == 409
    )
    # Compatibility only returns an ACK, never a new policy pin or broader authorization.
    app.state.service.settings = app.state.service.settings.model_copy(
        update={"max_model_calls": 1}
    )
    assert c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": key}).status_code == 409
    with app.state.store.transaction() as conn:
        execute(
            conn,
            "UPDATE execution.web_datasets SET enabled=false WHERE owner=:o",
            o=app.state.store.policy.owner,
        )
    assert c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": key}).status_code == 403


def test_healthy_orphan_capacity_does_not_quarantine_waiting_run(api, tmp_path, monkeypatch):
    import subprocess

    c, app, _ = api
    body = import_sample(c)
    run_id = c.post("/api/v1/tasks", json=body, headers={"Idempotency-Key": uuid4().hex}).json()[
        "run_id"
    ]
    store = app.state.store
    policy = tmp_path / "host.json"
    policy.write_text(store.policy.model_dump_json(), encoding="utf-8")
    original = subprocess.Popen
    launches = []

    def start(command, **kwargs):
        launches.append(command[3])
        kwargs["env"] = {**kwargs["env"], "DATAPILOT_LLM_MODE": "fake"}
        return original(command, **kwargs)

    monkeypatch.setattr("datapilot.web.worker.subprocess.Popen", start)
    dispatcher = Dispatcher(store, policy)
    try:
        with store.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lease:
            for i in range(store.policy.max_workers):
                execute(
                    lease,
                    "SELECT pg_advisory_lock(hashtextextended(:host,6156))",
                    host=store.policy.owner + ":" + str(i),
                )
            try:
                for _ in range(4):
                    dispatcher.poll()
                    for child in list(dispatcher.children.values()):
                        child.wait(timeout=30)
                row = store.run(run_id)
                assert row["command_seq"] > row["processed_seq"], row["last_error"]
                assert row["last_error"] is None
                assert launches == [], (
                    "full host capacity should wait without launching failed workers"
                )
            finally:
                for i in range(store.policy.max_workers):
                    execute(
                        lease,
                        "SELECT pg_advisory_unlock(hashtextextended(:host,6156))",
                        host=store.policy.owner + ":" + str(i),
                    )
        dispatcher.poll()
        for child in dispatcher.children.values():
            child.wait(timeout=90)
        dispatcher.poll()
        assert store.run(run_id)["status_hint"] == "awaiting_review"
    finally:
        for child in dispatcher.children.values():
            child.wait(timeout=90)
