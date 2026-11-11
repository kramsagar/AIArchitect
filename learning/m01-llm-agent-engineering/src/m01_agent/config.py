"""Runtime configuration. Every limit an agent needs in production is explicit and overridable via env."""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentConfig(BaseModel):
    provider: Literal["mock", "openai"] = "mock"
    model: str = "gpt-4o-mini"
    base_url: str | None = None  # any OpenAI-compatible endpoint (Azure proxy, vLLM, Ollama, LiteLLM)
    temperature: float = Field(default=0.0, ge=0, le=2)
    developer_role: Literal["developer", "system"] = "developer"  # use "system" for servers without it

    # Loop guards
    max_steps: int = Field(default=6, ge=1)
    max_tool_calls: int = Field(default=8, ge=1)
    max_repairs: int = Field(default=2, ge=0)

    # Time budgets (seconds)
    run_timeout_s: float = 60.0
    llm_timeout_s: float = 30.0
    tool_timeout_s: float = 2.0

    # Resilience
    llm_max_retries: int = 2
    tool_max_retries: int = 2
    retry_base_delay_s: float = 0.1
    breaker_threshold: int = 5
    breaker_reset_s: float = 30.0
    cache_ttl_s: float = 5.0

    # Memory
    memory_max_turns: int = 6
    memory_max_tokens: int = 1500

    @classmethod
    def from_env(cls, **overrides: Any) -> AgentConfig:
        env = {
            "provider": os.getenv("AGENT_PROVIDER"),
            "model": os.getenv("AGENT_MODEL"),
            "base_url": os.getenv("OPENAI_BASE_URL"),
            "developer_role": os.getenv("AGENT_DEVELOPER_ROLE"),
            "max_steps": os.getenv("AGENT_MAX_STEPS"),
            "run_timeout_s": os.getenv("AGENT_RUN_TIMEOUT_S"),
            "tool_timeout_s": os.getenv("AGENT_TOOL_TIMEOUT_S"),
        }
        values = {k: v for k, v in env.items() if v}
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls.model_validate(values)
