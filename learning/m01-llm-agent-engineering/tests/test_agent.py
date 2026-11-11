import pytest

from m01_agent import AgentConfig, AssistantResponse, build_agent
from m01_agent.errors import LLMError
from m01_agent.llm.base import LLMDecision
from m01_agent.llm.mock import MockLLM, detect_calculation
from m01_agent.schemas import ToolCall
from m01_agent.tools import MockMetricsBackend


def test_single_tool_run():
    r = build_agent().run("Is checkout-api healthy?")
    assert r.status == "completed"
    assert r.response.severity == "critical"
    assert r.response.tools_used == ["get_service_health"]
    assert r.usage.llm_calls == 2 and r.usage.tool_calls == 1


def test_two_hop_capacity_plan_uses_observed_numbers():
    r = build_agent().run("Can checkout-api handle 2x traffic?")
    calc = r.steps[1].tool_calls[0]
    assert calc.name == "capacity_calculator"
    assert "replicas_needed(24800" in calc.arguments
    assert r.response.intent == "health_and_capacity"
    assert "63 replicas" in r.response.answer


def test_parallel_tool_calls_in_one_step():
    r = build_agent().run("Compare payments-gateway and search-api")
    assert len(r.steps[0].tool_calls) == 2
    assert r.response.severity == "critical"


@pytest.mark.parametrize(
    "q,expr",
    [
        ("error budget for 99.9% over 28 days", "error_budget_minutes(99.9, 28)"),
        ("burn rate for 0.5% errors against 99.9% SLO", "burn_rate(0.5, 99.9)"),
        ("concurrency for 5,000 rps at 120 ms", "concurrency(5000, 120)"),
        ("replicas for 12000 tps at 800 tps per pod with 40% headroom", "replicas_needed(12000, 800, 40)"),
        ("availability with 3 redundant zones at 99.5%", "parallel_availability(99.5, 3)"),
        ("calculate `2*(3+4)`", "2*(3+4)"),
    ],
)
def test_mock_maps_questions_to_expressions(q, expr):
    assert detect_calculation(q) == expr


def test_memory_resolves_follow_up():
    agent = build_agent()
    agent.run("Is checkout-api healthy?")
    r = agent.run("Can it handle 3x traffic?")
    assert r.response.intent == "health_and_capacity"
    assert agent.memory.facts["last_service"] == "checkout-api"


def test_tool_failure_is_reported_not_raised():
    r = build_agent().run("Is billing-api healthy?")
    assert r.status == "completed"
    assert r.response.confidence == "low" and r.response.severity == "unknown"
    assert r.response.tools_used == []


def test_out_of_scope_and_ambiguous():
    assert build_agent().run("write a poem").response.intent == "unsupported"
    r = build_agent().run("p99 latency is spiking")
    assert r.response.follow_up and r.usage.tool_calls == 0


def test_repair_loop_recovers_from_invalid_output():
    r = build_agent(llm=MockLLM(invalid_output_times=1)).run("Is search-api healthy?")
    assert r.status == "completed"
    assert [s.decision for s in r.steps] == ["tool_calls", "invalid_output", "final"]


def test_repair_gives_up_and_fails_closed():
    r = build_agent(AgentConfig(max_repairs=1), llm=MockLLM(invalid_output_times=5)).run("Is search-api healthy?")
    assert r.status == "invalid_output"
    assert r.response.confidence == "low"


def test_loop_guards():
    r = build_agent(AgentConfig(max_steps=3), llm=MockLLM(loop_forever=True)).run("Is checkout-api ok?")
    assert r.status == "max_steps"
    assert r.usage.tool_calls == 1  # duplicates were not executed
    assert r.steps[1].observations[0].error_type == "duplicate_call"


def test_tool_budget():
    class Greedy:
        def decide(self, messages, tools, *, timeout_s):
            calls = [
                ToolCall(id=f"c{i}", name="capacity_calculator", arguments=f'{{"expression": "{i}+1"}}')
                for i in range(10)
            ]
            return LLMDecision(tool_calls=calls)

    r = build_agent(AgentConfig(max_tool_calls=5), llm=Greedy()).run("x")
    assert r.status == "tool_budget" and r.usage.tool_calls == 0


def test_llm_error_degrades_gracefully():
    class Down:
        def decide(self, messages, tools, *, timeout_s):
            raise LLMError("503 from provider")

    r = build_agent(llm=Down()).run("Is checkout-api healthy?")
    assert r.status == "llm_error"
    AssistantResponse.model_validate(r.response.model_dump())


def test_run_timeout():
    cfg = AgentConfig(run_timeout_s=0.2, tool_timeout_s=5, tool_max_retries=0, cache_ttl_s=0)
    r = build_agent(cfg, metrics_backend=MockMetricsBackend(latency_s=0.5)).run("Is search-api healthy?")
    assert r.status in {"timeout", "completed"}
    assert r.usage.elapsed_ms < 1500


def test_grounding_overrides_model_self_report():
    class Liar:
        n = 0

        def decide(self, messages, tools, *, timeout_s):
            self.n += 1
            return LLMDecision(
                content=AssistantResponse(
                    answer="all good",
                    intent="general",
                    severity="ok",
                    recommendations=[],
                    tools_used=["get_service_health", "capacity_calculator"],
                    confidence="high",
                    follow_up=None,
                ).model_dump_json()
            )

    r = build_agent(llm=Liar()).run("hi")
    assert r.response.tools_used == []


def test_openai_client_mapping():
    from types import SimpleNamespace as NS

    from m01_agent.llm.openai_llm import OpenAIChatLLM

    msg = NS(
        content=None,
        tool_calls=[
            NS(id="t1", function=NS(name="get_service_health", arguments='{"service":"a-api","window_minutes":5}'))
        ],
    )
    resp = NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=10, completion_tokens=3))
    captured = {}

    class FakeCompletions:
        def create(self, **kw):
            captured.update(kw)
            return resp

    fake = NS(chat=NS(completions=FakeCompletions()))
    d = OpenAIChatLLM(AgentConfig(provider="openai"), client=fake).decide(
        [{"role": "user", "content": "x"}], [], timeout_s=5
    )
    assert d.tool_calls[0].name == "get_service_health" and d.prompt_tokens == 10
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["temperature"] == 0.0


def test_anthropic_message_translation():
    from m01_agent.llm.anthropic_llm import to_anthropic

    system, msgs = to_anthropic(
        [
            {"role": "system", "content": "S"},
            {"role": "developer", "content": "D"},
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "a", "type": "function", "function": {"name": "t1", "arguments": '{"x": 1}'}},
                    {"id": "b", "type": "function", "function": {"name": "t2", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "a", "content": "r1"},
            {"role": "tool", "tool_call_id": "b", "content": "r2"},
        ]
    )
    assert system == "S\n\nD"
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1]["content"][0] == {"type": "tool_use", "id": "a", "name": "t1", "input": {"x": 1}}
    assert [b["tool_use_id"] for b in msgs[2]["content"]] == ["a", "b"]


def test_anthropic_client_mapping_end_to_end():
    from types import SimpleNamespace as NS

    from m01_agent.llm.anthropic_llm import AnthropicLLM

    final = AssistantResponse(
        answer="checkout-api is breaching its p99 SLO",
        intent="service_health",
        severity="critical",
        recommendations=["roll back"],
        tools_used=[],
        confidence="high",
        follow_up=None,
    ).model_dump_json()
    replies = iter(
        [
            NS(
                content=[
                    NS(
                        type="tool_use",
                        id="tu1",
                        name="get_service_health",
                        input={"service": "checkout-api", "window_minutes": 15},
                    )
                ],
                usage=NS(input_tokens=900, output_tokens=40),
            ),
            NS(content=[NS(type="text", text=final)], usage=NS(input_tokens=1200, output_tokens=80)),
        ]
    )
    sent = []

    class FakeMessages:
        def create(self, **kw):
            sent.append(kw)
            return next(replies)

    llm = AnthropicLLM(AgentConfig(provider="anthropic"), client=NS(messages=FakeMessages()))
    r = build_agent(AgentConfig(provider="anthropic"), llm=llm).run("Is checkout-api healthy?")
    assert r.status == "completed" and r.response.tools_used == ["get_service_health"]
    assert r.usage.prompt_tokens == 2100
    assert sent[0]["model"] == "claude-sonnet-5-5"
    assert sent[0]["output_config"]["format"]["type"] == "json_schema"
    assert sent[0]["tools"][0]["input_schema"]["type"] == "object"
    assert sent[1]["messages"][-1]["content"][0]["type"] == "tool_result"
