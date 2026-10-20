"""Mock HTTP protocol tests: real LangChain adapter/SDK, no real model inference."""

import httpx
from langchain_openai import ChatOpenAI

from datapilot.contracts import RouteDecision
from datapilot.harness.budget import RunBudget
from datapilot.llm.client import JSONModelClient


def test_openai_compatible_http_contract(settings):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "mock-response",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"route":"sql"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        chat = ChatOpenAI(
            model="test-model",
            api_key="mock-key-not-a-secret",
            base_url="https://model.invalid/v1",
            http_client=http,
            max_tokens=1200,
            timeout=1,
            max_retries=0,
            stream_usage=False,
        )
        budget = RunBudget(3, 18000)
        decision = JSONModelClient(chat, settings, budget).generate(
            RouteDecision, system="Route the task", user="查询客户总数"
        )
    assert decision.route == "sql" and budget.reported_tokens == 15
    assert len(requests) == 1 and requests[0].url.path == "/v1/chat/completions"
