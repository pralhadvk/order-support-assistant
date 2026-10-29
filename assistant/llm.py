"""Thin wrapper over OpenRouter's OpenAI-compatible chat completions API."""

from functools import lru_cache

from openai import OpenAI

from assistant.config import settings


class MissingAPIKeyError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    if not settings.openrouter_api_key:
        raise MissingAPIKeyError("OPENROUTER_API_KEY is not set. Copy .env.example to .env and add your key.")
    return OpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        default_headers={"X-Title": "Order Support Assistant"},
    )


def chat(messages: list[dict], tools: list[dict] | None = None, model: str | None = None):
    """Single chat-completion call. Returns the full response so callers can read usage and cost."""
    kwargs = {
        "model": model or settings.orchestrator_model,
        "messages": messages,
        "temperature": settings.temperature,
        # Without a cap OpenRouter reserves credit for the model's maximum output (65k tokens) on every call.
        "max_tokens": settings.max_output_tokens,
        "extra_body": {"usage": {"include": True}},  # OpenRouter adds the billed cost to `usage`
    }
    if tools:
        kwargs["tools"] = tools
    return get_client().chat.completions.create(**kwargs)
