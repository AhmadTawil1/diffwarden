from contextvars import ContextVar
from dataclasses import dataclass

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.config import settings
from app.prompts import REVIEW_SYSTEM, VERIFY_SYSTEM
from app.schema import FINDINGS_SCHEMA, VERDICTS_SCHEMA, Finding, Findings, Verdict, Verdicts

# The SDK only reads real env vars, not .env, so pass the key from settings. Retries 429/5xx automatically.
client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())


@dataclass
class Usage:
    """Tokens used by Claude calls; output tokens include thinking."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        return (self.input_tokens * settings.input_price_per_mtok
                + self.output_tokens * settings.output_price_per_mtok) / 1_000_000


# Set by track_usage(). asyncio tasks (including LangGraph's parallel nodes) copy the
# context, so every call made under one tracker adds to the same Usage object.
_usage: ContextVar[Usage | None] = ContextVar("llm_usage", default=None)


def track_usage() -> Usage:
    """Start counting tokens for the Claude calls made from the current task onward."""
    usage = Usage()
    _usage.set(usage)
    return usage


class BatchTooLarge(Exception):
    pass


class ModelRefused(Exception):
    pass


async def _structured(system: str, user: str, schema: dict, model: type[BaseModel]):
    res = await client.messages.create(
        model=settings.anthropic_model,
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    if (usage := _usage.get()) is not None:  # counted even if the reply is unusable: it was billed
        usage.calls += 1
        usage.input_tokens += res.usage.input_tokens
        usage.output_tokens += res.usage.output_tokens
    if res.stop_reason == "max_tokens":
        raise BatchTooLarge()  # the JSON is probably cut off
    if res.stop_reason == "refusal":
        raise ModelRefused(res.stop_details)
    text = next((b.text for b in res.content if b.type == "text"), None)
    return model.model_validate_json(text)


async def review(user_prompt: str) -> list[Finding]:
    return (await _structured(REVIEW_SYSTEM, user_prompt, FINDINGS_SCHEMA, Findings)).findings


async def verify(user_prompt: str) -> list[Verdict]:
    return (await _structured(VERIFY_SYSTEM, user_prompt, VERDICTS_SCHEMA, Verdicts)).verdicts
