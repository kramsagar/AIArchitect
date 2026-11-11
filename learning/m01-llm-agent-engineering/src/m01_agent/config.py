"""Runtime configuration. Every limit an agent needs in production is explicit and overridable via env."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

_INLINE_COMMENT = re.compile(r"\s+#.*$")


def load_dotenv(path: str | Path = ".env") -> dict[str, str]:
    """Load KEY=VALUE lines from a .env file into os.environ without overriding variables already set.

    Supports comments, inline `  # comments`, optional `export ` and quoted values. Returns what was loaded.
    """
    file = Path(path)
    if not file.is_file():
        return {}
    loaded: dict[str, str] = {}
    for raw in file.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] in {'"', "'"} and value[-1:] == value[:1] and len(value) > 1:
            value = value[1:-1]
        else:
            value = _INLINE_COMMENT.sub("", value).strip()
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


DEFAULT_MODELS = {"anthropic": "claude-sonnet-5-5", "openai": "gpt-4o-mini", "mock": "mock-sre-v1"}


class AgentConfig(BaseModel):
    provider: Literal["mock", "anthropic", "openai"] = "mock"
    model: str = ""  # empty -> DEFAULT_MODELS[provider]
    base_url: str | None = None  # custom endpoint (gateway/proxy, or vLLM/Ollama for the openai provider)
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_output_tokens: int = 1024
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

    @model_validator(mode="after")
    def _default_model(self) -> AgentConfig:
        if not self.model:
            self.model = DEFAULT_MODELS[self.provider]
        return self

    @classmethod
    def from_env(cls, **overrides: Any) -> AgentConfig:
        env = {
            "provider": os.getenv("AGENT_PROVIDER"),
            "model": os.getenv("AGENT_MODEL"),
            "base_url": os.getenv("AGENT_BASE_URL"),
            "developer_role": os.getenv("AGENT_DEVELOPER_ROLE"),
            "max_steps": os.getenv("AGENT_MAX_STEPS"),
            "run_timeout_s": os.getenv("AGENT_RUN_TIMEOUT_S"),
            "tool_timeout_s": os.getenv("AGENT_TOOL_TIMEOUT_S"),
        }
        values = {k: v for k, v in env.items() if v}
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls.model_validate(values)
