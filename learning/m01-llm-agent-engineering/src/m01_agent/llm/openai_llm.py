"""OpenAI Chat Completions client: native function calling + strict structured output in one request.

Chat Completions is used (rather than the Responses API) because every OpenAI-compatible server
(Azure, vLLM, Ollama, LiteLLM) speaks it."""

from __future__ import annotations

from typing import Any

from ..config import AgentConfig
from ..errors import LLMError
from ..jsonschema import strict_json_schema
from ..schemas import AssistantResponse, ToolCall
from ..tokens import count_message_tokens
from .base import LLMDecision


class OpenAIChatLLM:
    def __init__(self, config: AgentConfig, client: Any | None = None) -> None:
        import openai

        self._openai = openai
        self.config = config
        # The SDK retries connection errors, 408/409/429 and 5xx with backoff; we only add the app-level loop.
        self.client = client or openai.OpenAI(
            base_url=config.base_url, max_retries=config.llm_max_retries, timeout=config.llm_timeout_s
        )
        self.response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "assistant_response",
                "strict": True,
                "schema": strict_json_schema(AssistantResponse),
            },
        }

    def decide(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, timeout_s: float) -> LLMDecision:
        try:
            resp = self.client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=True,
                temperature=self.config.temperature,
                response_format=self.response_format,
                timeout=timeout_s,
            )
        except self._openai.APIError as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc

        msg = resp.choices[0].message
        calls = [
            ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
            for c in (msg.tool_calls or [])
        ]
        usage = getattr(resp, "usage", None)
        return LLMDecision(
            tool_calls=calls,
            content=msg.content,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or count_message_tokens(messages),
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )
