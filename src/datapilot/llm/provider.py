"""Small provider profiles; transport, tool authorization and budgets stay shared."""

from langchain_openai import ChatOpenAI

from datapilot.config import Settings


def create_chat_model(settings: Settings) -> ChatOpenAI:
    if not settings.api_key or not settings.model:
        raise ValueError("Live model requires an API key and model name")
    options = {"max_tokens": settings.max_output_tokens}
    if settings.model_provider == "deepseek":
        # langchain-openai 1.7.2 rewrites max_tokens to max_completion_tokens.
        # Public extra_body passes DeepSeek's native field without private SDK hooks.
        # Thinking needs reasoning_content round-tripping, outside this minimal profile.
        options = {
            "use_responses_api": False,
            "extra_body": {
                "max_tokens": settings.max_output_tokens,
                "thinking": {"type": "disabled"},
            },
        }
    return ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        temperature=0,
        timeout=settings.model_timeout_seconds,
        max_retries=0,
        stream_usage=False,
        **options,
    )
