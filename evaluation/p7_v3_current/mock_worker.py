"""Test-only in-container worker: inject ChatOpenAI http_async_client, then run current_worker."""

import atexit
import json
import runpy
import sys
import traceback
from functools import partial
from pathlib import Path

import httpx
from langchain_core.messages import convert_to_messages
from langchain_openai import ChatOpenAI
from report_recovery_probe import ReportDecisions

import datapilot.llm.provider as provider

COUNTS = {"received": 0, "validation_passed": 0, "response_returned": 0}
STATE = Path("/tmp/mock-state.json")


def report():
    STATE.write_text(json.dumps(COUNTS), encoding="utf-8")
    print("MOCK_HTTP_STATE=" + json.dumps(COUNTS), file=sys.stderr)


atexit.register(report)


async def handler(request):
    COUNTS["received"] += 1
    STATE.write_text(json.dumps(COUNTS), encoding="utf-8")
    try:
        if str(request.url) not in (
            "https://mock.invalid/v1/chat/completions",
            "https://mock.invalid/chat/completions",
        ):
            raise AssertionError("unexpected provider URL")
        body = json.loads(request.content)
        if body.get("model") != "deepseek-flash":
            raise AssertionError("wrong model")
        if body.get("thinking") != {"type": "disabled"}:
            raise AssertionError("thinking must be disabled")
        COUNTS["validation_passed"] += 1
        STATE.write_text(json.dumps(COUNTS), encoding="utf-8")
        config_path = Path(sys.argv[sys.argv.index("--config") + 1])
        config = json.loads(config_path.read_bytes())
        document_goal = config["report_scope"].get("document_goal")
        decisions = ReportDecisions(document_goal["question"] if document_goal else "")
        reply = await decisions.respond(
            convert_to_messages(body["messages"]), body.get("tools", [])
        )
        message = {"role": "assistant", "content": reply.content}
        if reply.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call["args"])},
                }
                for call in reply.tool_calls
            ]
        COUNTS["response_returned"] += 1
        STATE.write_text(json.dumps(COUNTS), encoding="utf-8")
        return httpx.Response(
            200,
            json={
                "id": "mock-live",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if reply.tool_calls else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )
    except BaseException:
        Path("/tmp/mock-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise


try:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider.ChatOpenAI = partial(ChatOpenAI, http_async_client=http)
    sys.argv = ["/bench/current_worker.py", *sys.argv[1:]]
    runpy.run_path("/bench/current_worker.py", run_name="__main__")
except BaseException:
    Path("/tmp/mock-wrapper-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    raise
