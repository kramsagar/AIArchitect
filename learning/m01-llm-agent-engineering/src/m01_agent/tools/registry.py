"""Tool registry + executor. The model only *proposes* calls; this layer validates, enforces budgets,
retries, caches and converts every failure into an Observation the model can reason about."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from ..errors import ToolError
from ..jsonschema import strict_json_schema
from ..resilience import CircuitBreaker, Deadline, RetryPolicy, TTLCache, call_with_timeout, retry_call
from ..schemas import Observation, ToolCall
from ..telemetry import METRICS, log_event, span


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[[Any], BaseModel]
    timeout_s: float | None = None
    idempotent: bool = True  # only idempotent (read-only) tools are retried or cached
    cache_ttl_s: float = 0.0

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": strict_json_schema(self.args_model),
                "strict": True,
            },
        }


def format_validation_error(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}" for e in exc.errors())


class ToolRegistry:
    def __init__(
        self,
        tools: list[Tool],
        *,
        timeout_s: float = 2.0,
        retry: RetryPolicy | None = None,
        breaker_threshold: int = 5,
        breaker_reset_s: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._tools = {t.name: t for t in tools}
        self.timeout_s = timeout_s
        self.retry = retry or RetryPolicy()
        self._sleep = sleep
        self.breakers = {t.name: CircuitBreaker(breaker_threshold, breaker_reset_s) for t in tools}
        self.caches = {t.name: TTLCache(t.cache_ttl_s) for t in tools if t.cache_ttl_s > 0}
        self._schemas = [t.schema() for t in tools]

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return self._schemas

    def execute(self, call: ToolCall, *, run_id: str = "-", deadline: Deadline | None = None) -> Observation:
        start = time.perf_counter()
        with span("tool", run_id, tool=call.name) as rec:
            obs = self._execute(call, deadline)
            obs.latency_ms = round((time.perf_counter() - start) * 1000, 2)
            rec.update(ok=obs.ok, error_type=obs.error_type, attempts=obs.attempts, cached=obs.cached)
        METRICS.inc(f"tool.{call.name}.{'ok' if obs.ok else obs.error_type}")
        return obs

    def _execute(self, call: ToolCall, deadline: Deadline | None) -> Observation:
        def fail(error: str, error_type: str, attempts: int = 0) -> Observation:
            return Observation(
                tool_call_id=call.id,
                tool_name=call.name,
                ok=False,
                error=error,
                error_type=error_type,
                attempts=attempts,
            )

        tool = self._tools.get(call.name)
        if tool is None:
            return fail(f"unknown tool '{call.name}'. Available: {', '.join(self._tools)}", "unknown_tool")
        try:
            args = tool.args_model.model_validate(json.loads(call.arguments or "{}"))
        except json.JSONDecodeError as exc:
            return fail(f"arguments are not valid JSON: {exc.msg}", "invalid_arguments")
        except ValidationError as exc:
            return fail(format_validation_error(exc), "invalid_arguments")

        cache = self.caches.get(tool.name)
        cache_key = args.model_dump_json()
        if cache is not None and (hit := cache.get(cache_key)) is not None:
            return Observation(tool_call_id=call.id, tool_name=tool.name, ok=True, output=hit, attempts=0, cached=True)

        timeout = tool.timeout_s or self.timeout_s
        if deadline is not None:
            if deadline.expired():
                return fail("run deadline exceeded before the tool could start", "deadline_exceeded")
            timeout = deadline.cap(timeout)
        policy = self.retry if tool.idempotent else RetryPolicy(max_retries=0)
        breaker = self.breakers[tool.name]
        attempts = 0

        def attempt() -> BaseModel:
            nonlocal attempts
            attempts += 1
            return breaker.call(lambda: call_with_timeout(lambda: tool.fn(args), timeout))

        try:
            result, _ = retry_call(attempt, policy, sleep=self._sleep, deadline=deadline)
        except ToolError as exc:
            return fail(str(exc), exc.error_type, attempts)
        except Exception as exc:  # a bug in the tool: log it, but do not leak internals to the model
            log_event("tool_crash", tool=tool.name, error=repr(exc))
            return fail(f"internal error in tool ({type(exc).__name__})", "internal_error", attempts)

        output = result.model_dump()
        if cache is not None:
            cache.put(cache_key, output)
        return Observation(tool_call_id=call.id, tool_name=tool.name, ok=True, output=output, attempts=attempts)
