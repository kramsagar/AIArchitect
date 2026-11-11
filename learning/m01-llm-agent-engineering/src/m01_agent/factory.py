"""Wires config -> tools -> registry -> LLM -> agent. Swap any piece (e.g. a real metrics client) here."""

from __future__ import annotations

import time
from collections.abc import Callable

from .agent import Agent
from .config import AgentConfig
from .llm.base import LLMClient
from .llm.mock import MockLLM
from .memory import ConversationMemory
from .resilience import RetryPolicy
from .schemas import CapacityCalcArgs, ServiceHealthArgs
from .tools.capacity import calculate
from .tools.registry import Tool, ToolRegistry
from .tools.service_health import MockMetricsBackend


def build_tools(config: AgentConfig, metrics_backend: Callable | None = None) -> list[Tool]:
    return [
        Tool(
            name="get_service_health",
            description=(
                "Get live golden signals for ONE service: rps, p50/p95/p99 latency, error rate, CPU, saturation, "
                "replicas, SLO targets, dependency status and the most recent change. Read-only."
            ),
            args_model=ServiceHealthArgs,
            fn=metrics_backend or MockMetricsBackend(),
            cache_ttl_s=config.cache_ttl_s,
        ),
        Tool(
            name="capacity_calculator",
            description=(
                "Evaluate SRE and capacity math exactly. Use it for ANY arithmetic: error budgets, burn rate, "
                "Little's-law concurrency, replicas needed for a target TPS, serial/parallel availability."
            ),
            args_model=CapacityCalcArgs,
            fn=calculate,
            timeout_s=0.5,
        ),
    ]


def build_registry(config: AgentConfig, metrics_backend: Callable | None = None, sleep=time.sleep) -> ToolRegistry:
    return ToolRegistry(
        build_tools(config, metrics_backend),
        timeout_s=config.tool_timeout_s,
        retry=RetryPolicy(max_retries=config.tool_max_retries, base_delay_s=config.retry_base_delay_s),
        breaker_threshold=config.breaker_threshold,
        breaker_reset_s=config.breaker_reset_s,
        sleep=sleep,
    )


def build_llm(config: AgentConfig) -> LLMClient:
    if config.provider == "anthropic":
        from .llm.anthropic_llm import AnthropicLLM

        return AnthropicLLM(config)
    if config.provider == "openai":
        from .llm.openai_llm import OpenAIChatLLM

        return OpenAIChatLLM(config)
    return MockLLM()


def build_agent(
    config: AgentConfig | None = None,
    *,
    llm: LLMClient | None = None,
    metrics_backend: Callable | None = None,
    with_memory: bool = True,
    sleep=time.sleep,
) -> Agent:
    config = config or AgentConfig()
    memory = ConversationMemory(config.memory_max_turns, config.memory_max_tokens) if with_memory else None
    return Agent(
        llm=llm or build_llm(config),
        registry=build_registry(config, metrics_backend, sleep),
        config=config,
        memory=memory,
    )
