"""LangChain OpenAI-compatible API, JSON contracts, bounded calls and safe failures."""

import json
from typing import Protocol, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from datapilot.config import Settings
from datapilot.contracts import AgentFailure
from datapilot.harness.budget import RunBudget
from datapilot.harness.context import check_context
from datapilot.llm.provider import create_chat_model

T = TypeVar("T", bound=BaseModel)


class ModelClient(Protocol):
    def generate(self, schema: type[T], *, system: str, user: str) -> T: ...


class JSONModelClient:
    """Invoke a LangChain chat model; JSON validation works without provider tool APIs."""

    def __init__(self, chat, settings: Settings, budget: RunBudget):
        self.chat = chat
        self.settings = settings
        self.budget = budget

    def generate(self, schema: type[T], *, system: str, user: str) -> T:
        system += "\nReturn only one JSON object matching: " + json.dumps(
            schema.model_json_schema()
        )
        check_context(system, user, self.settings.max_input_chars)
        reservation = self.budget.reserve(system + user, self.settings.max_output_tokens)
        try:
            response = self.chat.invoke([SystemMessage(content=system), HumanMessage(content=user)])
        except Exception as exc:
            self.budget.settle(reservation, None)
            # Never echo raw provider exceptions: URLs/headers may contain credentials.
            raise AgentFailure("MODEL_ERROR", "Model request failed or timed out") from exc
        usage = (response.usage_metadata or {}).get("total_tokens")
        self.budget.settle(reservation, usage if isinstance(usage, int) and usage >= 0 else None)
        if not isinstance(response.content, str):
            raise AgentFailure("MODEL_OUTPUT_INVALID", "Model must return JSON text")
        if len(response.content) > self.settings.max_output_tokens * 16:
            raise AgentFailure("MODEL_OUTPUT_INVALID", "Model response exceeded its size limit")
        try:
            return schema.model_validate_json(response.content)
        except (ValidationError, ValueError) as exc:
            raise AgentFailure(
                "MODEL_OUTPUT_INVALID", "Model response failed JSON contract validation"
            ) from exc


def create_live_client(settings: Settings, budget: RunBudget) -> JSONModelClient:
    return JSONModelClient(create_chat_model(settings), settings, budget)
