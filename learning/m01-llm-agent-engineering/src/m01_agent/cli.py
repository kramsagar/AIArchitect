"""CLI: `m01-agent ask "..."`, `m01-agent chat`, `m01-agent bench`, `m01-agent schemas`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from .config import AgentConfig
from .factory import build_agent
from .schemas import AgentResult
from .telemetry import METRICS, percentile

BENCH_QUESTIONS = [
    "Is checkout-api healthy?",
    "Compare payments-gateway and search-api",
    "Can auth-service handle 3x traffic?",
    "What's the error budget for 99.95% over 30 days?",
    "Concurrency for 12000 rps at 45 ms?",
]


def _print_result(result: AgentResult, *, trace: bool, as_json: bool) -> None:
    if as_json:
        print(result.model_dump_json(indent=2))
        return
    if trace:
        for s in result.steps:
            print(f"  [step {s.step}] decide -> {s.decision}" + (f" ({s.note})" if s.note else ""))
            for c, o in zip(s.tool_calls, s.observations, strict=False):
                status = "ok" if o.ok else f"{o.error_type}: {o.error}"
                extra = " cached" if o.cached else f" attempts={o.attempts}"
                print(f"      act {c.name}({c.arguments}) -> {status} [{o.latency_ms}ms{extra}]")
    r = result.response
    print(f"\n[{r.severity.upper()}] {r.answer}")
    for i, rec in enumerate(r.recommendations, 1):
        print(f"  {i}. {rec}")
    if r.follow_up:
        print(f"  ? {r.follow_up}")
    u = result.usage
    print(
        f"\nstatus={result.status} intent={r.intent} confidence={r.confidence} tools={r.tools_used} "
        f"llm_calls={u.llm_calls} tool_calls={u.tool_calls} tokens={u.prompt_tokens}+{u.completion_tokens} "
        f"elapsed={u.elapsed_ms}ms run_id={result.run_id}"
    )


def cmd_ask(args: argparse.Namespace, config: AgentConfig) -> int:
    if args.sdk:
        from .sdk_agent import run_sdk

        print(run_sdk(args.question, config).model_dump_json(indent=2))
        return 0
    result = build_agent(config).run(args.question)
    _print_result(result, trace=args.trace, as_json=args.json)
    return 0 if result.status == "completed" else 2


def cmd_chat(args: argparse.Namespace, config: AgentConfig) -> int:
    agent = build_agent(config)
    print("SRE Copilot (memory on). Try: 'Is checkout-api healthy?' then 'Can it handle 2x traffic?'. Ctrl+C quits.")
    while True:
        try:
            question = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if question in {"exit", "quit"}:
            return 0
        if question == "/reset":
            agent.memory.clear()
            print("memory cleared")
            continue
        if question:
            _print_result(agent.run(question), trace=args.trace, as_json=False)


def cmd_bench(args: argparse.Namespace, config: AgentConfig) -> int:
    """Measures the agent runtime itself (mock LLM by default): overhead latency and throughput under load."""
    from .llm.mock import MockLLM
    from .tools.service_health import MockMetricsBackend

    METRICS.reset()
    llm = MockLLM(latency_s=args.llm_latency_ms / 1000) if config.provider == "mock" else None
    backend = MockMetricsBackend(latency_s=args.tool_latency_ms / 1000, failure_rate=args.failure_rate, seed=7)
    agent = build_agent(config, llm=llm, metrics_backend=backend, with_memory=False)
    questions = [BENCH_QUESTIONS[i % len(BENCH_QUESTIONS)] for i in range(args.requests)]

    def one(q: str) -> tuple[float, str]:
        t = time.perf_counter()
        r = agent.run(q)
        return (time.perf_counter() - t) * 1000, r.status

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(one, questions))
    wall = time.perf_counter() - started
    lat = [r[0] for r in results]
    statuses: dict[str, int] = {}
    for _, s in results:
        statuses[s] = statuses.get(s, 0) + 1
    cache = agent.registry.caches.get("get_service_health")
    report = {
        "requests": args.requests,
        "concurrency": args.concurrency,
        "throughput_rps": round(args.requests / wall, 1),
        "latency_ms": {p: round(percentile(lat, n), 2) for p, n in (("p50", 50), ("p95", 95), ("p99", 99))},
        "statuses": statuses,
        "health_cache_hit_ratio": round(cache.hits / max(1, cache.hits + cache.misses), 3) if cache else None,
        "spans": METRICS.summary()["latency"],
    }
    print(json.dumps(report, indent=2))
    return 0


def cmd_schemas(args: argparse.Namespace, config: AgentConfig) -> int:
    from .jsonschema import strict_json_schema
    from .schemas import AssistantResponse

    agent = build_agent(config)
    print(
        json.dumps({"tools": agent.registry.schemas(), "final_output": strict_json_schema(AssistantResponse)}, indent=2)
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="m01-agent", description="SRE Copilot - single agent with two tools")
    parser.add_argument(
        "--provider", choices=["mock", "anthropic", "openai"], help="LLM backend (default: env or mock)"
    )
    parser.add_argument("--model", help="model name (default: claude-sonnet-4-5 / gpt-4o-mini)")
    parser.add_argument("-v", "--verbose", action="store_true", help="emit structured JSON span logs to stderr")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ask", help="ask one question")
    p.add_argument("question")
    p.add_argument("--trace", action="store_true", help="print each Observe/Decide/Act step")
    p.add_argument("--json", action="store_true", help="print the full AgentResult as JSON")
    p.add_argument("--sdk", action="store_true", help="run the OpenAI Agents SDK version instead")
    p.set_defaults(fn=cmd_ask)

    p = sub.add_parser("chat", help="interactive session with memory")
    p.add_argument("--trace", action="store_true")
    p.set_defaults(fn=cmd_chat)

    p = sub.add_parser("bench", help="concurrency benchmark of the agent runtime")
    p.add_argument("--requests", type=int, default=500)
    p.add_argument("--concurrency", type=int, default=32)
    p.add_argument("--llm-latency-ms", type=float, default=0.0, help="simulated LLM latency per call")
    p.add_argument("--tool-latency-ms", type=float, default=0.0, help="simulated metrics backend latency")
    p.add_argument("--failure-rate", type=float, default=0.0, help="metrics backend transient failure rate")
    p.set_defaults(fn=cmd_bench)

    p = sub.add_parser("schemas", help="print the tool schemas and final-output schema sent to the model")
    p.set_defaults(fn=cmd_schemas)

    args = parser.parse_args(argv)
    if args.verbose:
        logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    config = AgentConfig.from_env(provider=args.provider, model=args.model)
    return args.fn(args, config)
