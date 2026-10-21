"""Real LangChain/OpenAI SDK, intercepted HTTP; never calls a provider."""

import json
from functools import partial

import httpx
import pytest
from langchain_openai import ChatOpenAI
from test_deepseek_transport import completion, config
from test_rag_completion import QUESTION, RetrievalDouble

from datapilot.llm import provider
from datapilot.orchestration.contracts import Plan, TaskSpec
from datapilot.orchestration.coordinator import Coordinator
from datapilot.orchestration.model import live_transport


@pytest.mark.parametrize("bad", ["plain", "invalid_json"])
async def test_native_completion_and_stop_hook_preserve_wire_tool_pairs(monkeypatch, bad):
    requests = []

    async def respond(request):
        raw = json.loads(request.content)
        requests.append(raw)
        assert raw["thinking"] == {"type": "disabled"}
        messages = raw["messages"]
        if messages[0]["content"].startswith("PLAN_JSON"):
            return completion(
                {
                    "role": "assistant",
                    "content": Plan(
                        tasks=[
                            TaskSpec(
                                task_id="rag",
                                worker="rag",
                                instruction=QUESTION,
                            )
                        ]
                    ).model_dump_json(),
                }
            )
        observations = [m for m in messages if m["role"] == "tool"]
        calls = [c for m in messages for c in m.get("tool_calls", [])]
        for call in calls:
            assert sum(m["tool_call_id"] == call["id"] for m in observations) == 1
        corrected = any(m.get("name") == "rag_completion_gate" for m in messages)
        if not observations:
            name, args, id_ = "search_documents", '{"query":"入门培训","top_k":1}', "retrieve"
        elif not corrected:
            if bad == "plain":
                return completion({"role": "assistant", "content": "检索完成。"})
            name, args, id_ = "submit_rag_result", "{malformed", "invalid-native-submit"
        else:
            artifact = next(
                json.loads(m["content"])["artifact_refs"][0]["artifact_id"]
                for m in observations
                if json.loads(m["content"]).get("artifact_refs")
            )
            if bad == "invalid_json":
                original = next(c for c in calls if c["id"] == "invalid-native-submit")
                assert original["function"]["arguments"] == "{malformed"
            name, args, id_ = (
                "submit_rag_result",
                json.dumps(
                    {
                        "artifact_ids": [artifact],
                        "outcome": "complete",
                    }
                ),
                "valid-native-submit",
            )
        return completion(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": id_,
                        "type": "function",
                        "function": {"name": name, "arguments": args},
                    }
                ],
            }
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        monkeypatch.setattr(provider, "ChatOpenAI", partial(ChatOpenAI, http_async_client=http))
        settings = config(max_worker_turns=6, max_total_tokens=100000)
        engine = Coordinator(
            settings, live_transport(settings), retrieval=RetrievalDouble(), run_id="http-unit"
        )
        result = await engine.graph.ainvoke(
            {
                "run_id": "http-unit",
                "question": QUESTION,
                "status": "pending",
                "results": {},
                "verifications": {},
                "steps": 0,
                "replans": 0,
                "error": None,
            }
        )
    assert result["completion"].status == "completed"
    assert len(requests) == 4 and engine.ledger.snapshot().reported_tokens == 120
    assert result["results"]["1:rag"].rag_completion.verdict == "literal_locator"
