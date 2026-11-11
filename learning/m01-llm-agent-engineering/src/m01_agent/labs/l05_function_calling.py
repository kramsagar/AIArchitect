"""Lab 5 - function calling: tool schemas, a model's tool call, and safe dispatch.

Run: python -m m01_agent.labs.l05_function_calling"""

from __future__ import annotations

import json

from ..config import AgentConfig
from ..factory import build_registry
from ..schemas import ToolCall


def main() -> None:
    registry = build_registry(AgentConfig())
    print("== Tool schemas the model sees ==")
    print(json.dumps(registry.schemas(), indent=2)[:1400], "...")

    calls = [
        ToolCall(id="c1", name="get_service_health", arguments='{"service": "checkout-api", "window_minutes": 15}'),
        ToolCall(id="c2", name="capacity_calculator", arguments='{"expression": "concurrency(12400, 620)"}'),
        ToolCall(id="c3", name="get_service_health", arguments='{"service": "checkout-api"'),  # truncated JSON
        ToolCall(id="c4", name="get_service_health", arguments='{"service": "", "window_minutes": 99999}'),
        ToolCall(id="c5", name="capacity_calculator", arguments="{\"expression\": \"__import__('os').system('id')\"}"),
        ToolCall(id="c6", name="restart_pod", arguments='{"pod": "checkout-7f9c"}'),  # hallucinated tool
    ]
    print("\n== Dispatch: every failure becomes an Observation, never a crash ==")
    for c in calls:
        o = registry.execute(c)
        shown = json.dumps(o.output)[:110] if o.ok else f"{o.error_type}: {o.error}"
        print(f"  {c.name}({c.arguments[:55]}) -> {'OK ' if o.ok else 'ERR'} {shown}")


if __name__ == "__main__":
    main()
