"""Collector metadata must distinguish real Live from scripted/Fake execution."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from datapilot.config import Settings


@pytest.mark.parametrize(
    "mode,status", [("fake", "not_applicable_fake"), ("live", "not_reconciled")]
)
async def test_collection_cost_status_follows_execution_mode(monkeypatch, mode, status):
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import p7_business_runtime as runtime
    from p7_business_scoring import authenticated, sign_collection

    class Backend:
        def __init__(self, *_):
            pass

        def lease(self):
            return nullcontext(None)

        transaction = lease

        def authorize(self, _):
            return {"manifest_hash": "a" * 64, "manifest": {}, "cancelled": False}

        def close(self):
            pass

    class Rows:
        def mappings(self):
            return self

        def scalars(self):
            return self

        def all(self):
            return []

    async def inspect(*_, **__):
        return {"unknown": False, "usage": {"calls": 0, "total_tokens": 0}}

    monkeypatch.setattr(runtime, "Backend", Backend)
    monkeypatch.setattr(runtime, "DurableArtifacts", lambda _: SimpleNamespace(export=lambda: {}))
    monkeypatch.setattr(runtime, "execute", lambda *_args, **_kwargs: Rows())
    monkeypatch.setattr(runtime, "inspect_run", inspect)
    settings = Settings(
        _env_file=None,
        llm_mode=mode,
        api_key="public-synthetic-never-sent" if mode == "live" else None,
        model="public-synthetic-model" if mode == "live" else "",
        runtime_database_url="postgresql+psycopg://datapilot_runtime:public-test@127.0.0.1/test",
    )
    payload = await runtime.collect(
        {"run_id": "cost-control", "case_id": "public-control", "question_sha256": "b" * 64},
        settings,
        SimpleNamespace(owner="public-control", question="public control"),
        None,
    )
    key = b"public-synthetic-collector-key-32b"
    record = sign_collection(payload, key)
    observed = authenticated(record, key)
    assert observed["model_mode"] == mode
    assert observed["actual_provider_cost"] is None
    assert observed["actual_provider_cost_status"] == status
    record["payload"]["actual_provider_cost_status"] = "fabricated_bill"
    with pytest.raises(ValueError):
        authenticated(record, key)
