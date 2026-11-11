"""Anthropic Claude client: native tool use + structured outputs, mapped onto the provider-neutral loop.

The agent keeps an OpenAI-style message list (system/developer/user/assistant+tool_calls/tool). This adapter
translates it to the Messages API shape:
- system + developer messages -> the top-level `system` parameter (Claude has no developer role)
- assistant tool_calls        -> `tool_use` content blocks
- consecutive tool results    -> ONE user message with `tool_result` blocks
- final answer                -> `output_config.format` JSON schema (AssistantResponse), validated again by the agent
"""

from __future__ import annotations

import json
from typing import Any

from ..config import AgentConfig
from ..errors import LLMError
from ..jsonschema import strict_json_schema
from ..schemas import AssistantResponse, ToolCall
from ..tokens import count_message_tokens
from .base import LLMDecision

try:  # strips JSON-schema keywords Claude's constrained decoding does not support
    from anthropic import transform_schema
except ImportError:  # pragma: no cover
    from anthropic.lib._parse._transform import transform_schema


def to_anthropic(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []

    def push(role: str, blocks: list[dict[str, Any]]) -> None:
        if out and out[-1]["role"] == role:  # Claude requires alternating roles
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})

    for m in messages:
        role, content = m["role"], m.get("content")
        if role in ("system", "developer"):
            system_parts.append(content or "")
        elif role == "tool":
            push("user", [{"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": content or ""}])
        elif role == "assistant":
            blocks: list[dict[str, Any]] = [{"type": "text", "text": content}] if content else []
            for c in m.get("tool_calls") or []:
                fn = c["function"]
                try:
                    args = json.loads(fn["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                blocks.append({"type": "tool_use", "id": c["id"], "name": fn["name"], "input": args})
            push("assistant", blocks or [{"type": "text", "text": ""}])
        else:
            push("user", [{"type": "text", "text": content or ""}])
    return "\n\n".join(system_parts), out


def to_anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"].get("description", ""),
            "input_schema": transform_schema(t["function"]["parameters"]),
        }
        for t in tools
    ]


class AnthropicLLM:
    def __init__(self, config: AgentConfig, client: Any | None = None) -> None:
        import anthropic

        self._anthropic = anthropic
        self.config = config
        # The SDK retries connection errors, 408/409/429 and 5xx with backoff; we only add the app-level loop.
        self.client = client or anthropic.Anthropic(
            base_url=config.base_url,
            max_retries=config.llm_max_retries,
            timeout=config.llm_timeout_s,
        )
        self.output_format = {"type": "json_schema", "schema": transform_schema(strict_json_schema(AssistantResponse))}

    def decide(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, timeout_s: float) -> LLMDecision:
        system, msgs = to_anthropic(messages)
        try:
            resp = self.client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_output_tokens,
                system=system,
                messages=msgs,
                tools=to_anthropic_tools(tools),
                tool_choice={"type": "auto"},
                output_config={"format": self.output_format},
                timeout=timeout_s,
            )
        except self._anthropic.APIError as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc

        calls, texts = [], []
        for block in resp.content:
            if block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, arguments=json.dumps(block.input)))
            elif block.type == "text":
                texts.append(block.text)
        usage = getattr(resp, "usage", None)
        return LLMDecision(
            tool_calls=calls,
            content="".join(texts) or None,
            prompt_tokens=getattr(usage, "input_tokens", 0) or count_message_tokens(messages),
            completion_tokens=getattr(usage, "output_tokens", 0) or 0,
        )
