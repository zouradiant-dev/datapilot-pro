"""Real SDK HTTP mocks + original PG Journal; no actual provider requests."""

import asyncio
import json
import os
from functools import partial
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from langchain_openai import ChatOpenAI
from pydantic import ValidationError
from test_deepseek_transport import completion, config

from datapilot.contracts import AgentFailure
from datapilot.llm import provider
from datapilot.orchestration.contracts import BudgetLimits
from datapilot.orchestration.model import Gateway, live_transport
from datapilot.persistence.backend import Backend, DurableArtifacts, DurableLedger, execute
from datapilot.persistence.journal import Journal
from datapilot.persistence.session import PersistentCancellation

pytestmark = pytest.mark.integration
CASES = [
    "401",
    "403",
    "429",
    "500",
    "502",
    "503",
    "504",
    "connect",
    "read_timeout",
    "cancel",
    pytest.param(
        "bad_usage",
        marks=pytest.mark.xfail(
            strict=True,
            reason=(
                "P7 finding: malformed usage commits; cached replay raises untyped ValidationError"
            ),
        ),
    ),
    "missing_usage",
    "null_content",
    "incomplete_tool_call",
]


@pytest.mark.parametrize("fault", CASES)
async def test_http_fault_preserves_original_journal_budget_and_no_duplicate_attempt(
    pg_settings, monkeypatch, fault
):
    if os.environ.get("DATAPILOT_P7_ISOLATED") != "1":
        pytest.skip("P7 fault matrix runs only in its explicitly isolated PG instance")
    calls = []
    settings = config(
        runtime_database_url=pg_settings.runtime_database_url,
        model_timeout_seconds=0.05,
        max_output_tokens=512,
    )
    backend = Backend(settings.runtime_database_url.get_secret_value(), str(uuid4()), "p7-http")
    try:
        with backend.lease():
            limits = BudgetLimits(calls=2, tokens=12000)
            backend.register({"purpose": "p7-http-fault", "fault": fault}, limits)
            ledger = DurableLedger(backend, limits)
            journal = Journal(backend, ledger, DurableArtifacts(backend))
            cancel = PersistentCancellation(backend)

            async def respond(request):
                calls.append(request)
                assert json.loads(request.content)["thinking"] == {"type": "disabled"}
                if fault.isdigit():
                    return httpx.Response(int(fault), json={"error": {"message": "synthetic"}})
                if fault == "connect":
                    raise httpx.ConnectError("synthetic connect failure", request=request)
                if fault == "read_timeout":
                    raise httpx.ReadTimeout("synthetic timeout", request=request)
                if fault == "cancel":
                    asyncio.get_running_loop().call_later(0.01, cancel.cancel)
                    await asyncio.sleep(10)
                if fault == "bad_usage":
                    response = completion({"role": "assistant", "content": "{}"})
                    body = json.loads(response.content)
                    body["usage"]["total_tokens"] = "malformed"
                    return httpx.Response(200, json=body)
                if fault == "missing_usage":
                    return completion(
                        {"role": "assistant", "content": '{"tasks":[],"unsupported":true}'},
                        usage=False,
                    )
                if fault == "null_content":
                    return completion({"role": "assistant", "content": None})
                return completion(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "broken",
                                "type": "function",
                                "function": {"name": "query_database", "arguments": "{"},
                            }
                        ],
                    }
                )

            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
                monkeypatch.setattr(
                    provider, "ChatOpenAI", partial(ChatOpenAI, http_async_client=http)
                )
                gateway = Gateway(live_transport(settings), settings, ledger, cancel)
                gateway.durability = journal
                codes = []
                for _ in range(2):
                    try:
                        await gateway.plan("Synthetic protocol failure", {"sql"})
                        codes.append(None)
                    except AgentFailure as exc:
                        codes.append(exc.error.code)
                    except ValidationError:
                        codes.append("UNHANDLED_VALIDATION_ERROR")
                    if fault == "cancel":
                        assert backend.cancelled()
            with backend.transaction() as conn:
                rows = (
                    execute(
                        conn,
                        "SELECT status,usage FROM execution.calls WHERE run_id=:r",
                        r=backend.run_id,
                    )
                    .mappings()
                    .all()
                )
            assert len(calls) == 1 and len(rows) == 1
            assert ledger.snapshot().calls == 1 and ledger.snapshot().total_tokens > 0
            if fault == "bad_usage":
                assert rows[0]["status"] == "complete" and not ledger.snapshot().usage_complete
            elif fault in {"null_content", "incomplete_tool_call"}:
                assert rows[0]["status"] == "complete"
                assert codes[0] in {"PLAN_INVALID", "MODEL_OUTPUT_INVALID"}
                assert codes[1] == codes[0]  # Same invalid committed response; not a new HTTP call.
            elif fault == "missing_usage":
                assert rows[0]["status"] == "complete" and not ledger.snapshot().usage_complete
                assert codes == [None, None]  # Known response, unknown billing remains reserved.
            else:
                assert rows[0]["status"] == "uncertain"
                assert not ledger.snapshot().usage_complete
                assert codes[1] in {"RECOVERY_UNCERTAIN", "CANCELLED"}
            output = Path(__file__).resolve().parents[1] / "artifacts/p7/provider-faults"
            output.mkdir(parents=True, exist_ok=True)
            (output / (fault + "-" + backend.run_id + ".json")).write_text(
                json.dumps(
                    {
                        "fault": fault,
                        "run_id": backend.run_id,
                        "http_mock_attempts": len(calls),
                        "error_codes": codes,
                        "journal_status": rows[0]["status"],
                        "usage": ledger.snapshot().model_dump(),
                        "extra_attempts": 0,
                        "paid_calls": 0,
                        "provider_invoice": None,
                        "real_sdk_mock_with_pg_journal": True,
                        "typed_replay_contract_passed": "UNHANDLED_VALIDATION_ERROR" not in codes,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            assert "UNHANDLED_VALIDATION_ERROR" not in codes, (
                "Known P7 finding; not repaired by evaluation"
            )
    finally:
        backend.close()
