"""Lab 7 - agent state, memory, retries, timeouts, circuit breaker, loop guards.

Run: python -m m01_agent.labs.l07_resilience"""

from __future__ import annotations

from ..config import AgentConfig
from ..factory import build_agent
from ..llm.mock import MockLLM
from ..schemas import AgentResult
from ..tools.service_health import MockMetricsBackend


def show(title: str, r: AgentResult) -> None:
    print(f"\n== {title} ==")
    for s in r.steps:
        for o in s.observations:
            print(f"   tool {o.tool_name}: ok={o.ok} attempts={o.attempts} {o.error_type or ''} {o.latency_ms}ms")
    print(f"   status={r.status} confidence={r.response.confidence}: {r.response.answer[:140]}")


def main() -> None:
    cfg = AgentConfig(tool_timeout_s=0.3, retry_base_delay_s=0.05, cache_ttl_s=0)

    flaky = build_agent(cfg, metrics_backend=MockMetricsBackend(fail_first_n=2))
    show(
        "1. Transient 503 x2 -> retried with exponential backoff + jitter, then succeeds",
        flaky.run("Is checkout-api healthy?"),
    )

    slow = build_agent(cfg, metrics_backend=MockMetricsBackend(latency_s=1.0))
    show(
        "2. Slow backend (1s) vs 0.3s timeout -> timeout, retried, then reported honestly",
        slow.run("Is search-api healthy?"),
    )

    down = build_agent(
        AgentConfig(tool_max_retries=0, breaker_threshold=3, cache_ttl_s=0),
        metrics_backend=MockMetricsBackend(failure_rate=1.0),
    )
    for i in range(4):
        r = down.run("Is auth-service healthy?")
        o = r.steps[0].observations[0]
        print(f"   3.{i + 1} outage: breaker={down.registry.breakers['get_service_health'].state:<9} -> {o.error_type}")

    looping = build_agent(AgentConfig(max_steps=4), llm=MockLLM(loop_forever=True))
    show("4. Model stuck repeating the same call -> duplicate guard + max_steps", looping.run("Is checkout-api ok?"))

    bad_json = build_agent(llm=MockLLM(invalid_output_times=1))
    show("5. Invalid structured output -> schema errors fed back -> repaired", bad_json.run("Is search-api ok?"))

    agent = build_agent()
    agent.run("Is checkout-api healthy?")
    show("6. Memory: 'it' resolves to the service from the previous turn", agent.run("Can it handle 3x traffic?"))
    print(f"   memory facts={agent.memory.facts} turns={len(agent.memory.turns)}")


if __name__ == "__main__":
    main()
