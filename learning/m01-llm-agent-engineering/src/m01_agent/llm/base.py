from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from ..schemas import ToolCall


class LLMDecision(BaseModel):
    """One model turn: either tool calls to execute, or final content (expected to be AssistantResponse JSON)."""

    tool_calls: list[ToolCall] = Field(default_factory=list)
    content: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMClient(Protocol):
    def decide(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, timeout_s: float
    ) -> LLMDecision: ...
