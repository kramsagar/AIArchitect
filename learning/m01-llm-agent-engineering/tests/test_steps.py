"""Offline tests for the step-by-step track (steps/). A scripted fake client replaces Claude."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "steps"))

import step03_tool_schema as s3  # noqa: E402
import step05_agent_loop as s5  # noqa: E402
import step06_two_tools as s6  # noqa: E402
import step07_tool_errors as s7  # noqa: E402
import step08_timeouts_retries as s8  # noqa: E402
import step09_breaker_cache as s9  # noqa: E402
import step10_memory as s10  # noqa: E402
import step11_final_agent as s11  # noqa: E402
from pydantic import ValidationError  # noqa: E402


def tool_use(name, args, id_="t1"):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=args)


def text(t):
    return SimpleNamespace(type="text", text=t)


class FakeClient:
    """Returns scripted responses in order and records every request."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        content = self.responses.pop(0)
        stop = "tool_use" if any(b.type == "tool_use" for b in content) else "end_turn"
        return SimpleNamespace(content=content, stop_reason=stop)


def test_step03_tool_validates_arguments_and_service():
    assert s3.HEALTH_TOOL.run({"service": "checkout-api"})["replicas"] == 24
    with pytest.raises(ValidationError):
        s3.HEALTH_TOOL.run({"svc": "checkout-api"})
    with pytest.raises(LookupError):
        s3.HEALTH_TOOL.run({"service": "nope"})
    assert s3.HEALTH_TOOL.spec()["input_schema"]["required"] == ["service"]


def test_step05_loop_runs_tool_then_returns_final_answer():
    c = FakeClient([tool_use("get_service_health", {"service": "checkout-api"})], [text("checkout-api is critical")])
    assert s5.run_agent(c, "is checkout ok?", trace=False) == "checkout-api is critical"
    tool_result = c.requests[1]["messages"][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and '"p99_ms": 620' in tool_result["content"]


def test_step05_max_steps_guard():
    c = FakeClient(*[[tool_use("get_service_health", {"service": "search-api"}, f"t{i}")] for i in range(3)])
    assert s5.run_agent(c, "loop", max_steps=3, trace=False).startswith("Stopped")


def test_step06_safe_eval_math_and_rejections():
    assert s6.safe_eval("replicas_needed(12400*2, 12400/24, 30)") == 63
    assert s6.safe_eval("burn_rate(0.42, 99.95)") == pytest.approx(8.4)
    for evil in ("__import__('os').system('ls')", "2**999999", "open('x')"):
        with pytest.raises(ValueError):
            s6.safe_eval(evil)


@pytest.mark.parametrize(
    "name,args,expected",
    [
        ("nope", {}, "unknown tool"),
        ("get_service_health", {"name": "x"}, "invalid arguments"),
        ("get_service_health", {"service": "checkout"}, "LookupError"),
        ("capacity_calculator", {"expression": "open('x')"}, "ValueError"),
    ],
)
def test_step07_errors_become_observations(name, args, expected):
    result = s7.safe_execute(tool_use(name, args), s6.TOOLS)
    assert result["is_error"] is True and expected in result["content"]


def test_step08_retry_then_success_and_timeout():
    args = s3.ServiceHealthArgs(service="checkout-api")
    flaky = s8.FlakyMetrics(fail_first=2, latency_s=0)
    result, attempts = s8.retry(lambda: flaky(args), sleep=lambda _: None)
    assert attempts == 3 and result["service"] == "checkout-api"
    with pytest.raises(s7.TransientError):
        s8.retry(lambda: s8.FlakyMetrics(fail_first=9, latency_s=0)(args), sleep=lambda _: None)
    with pytest.raises(s7.TransientError, match="timed out"):
        s8.with_timeout(lambda: __import__("time").sleep(0.3), 0.05)


def test_step09_breaker_opens_and_cache_hits():
    now = [0.0]
    breaker = s9.CircuitBreaker(threshold=2, reset_s=10, clock=lambda: now[0])

    def boom():
        raise s7.TransientError("503")

    for _ in range(2):
        with pytest.raises(s7.TransientError):
            breaker.call(boom)
    with pytest.raises(s9.CircuitOpen):
        breaker.call(lambda: "never called")
    now[0] = 11
    assert breaker.call(lambda: "ok") == "ok"

    cache = s9.TTLCache(ttl_s=5, clock=lambda: now[0])
    cache.put("k", 1)
    assert cache.get("k") == 1
    now[0] += 6
    assert cache.get("k") is None


def test_step10_memory_keeps_last_turns_only():
    m = s10.Memory(max_turns=2)
    for i in range(3):
        m.add(f"q{i}", f"a{i}")
    assert [x["content"] for x in m.messages()] == ["q1", "a1", "q2", "a2"]


def test_step11_repairs_invalid_json_and_grounds_audit_fields():
    good = (
        '{"answer": "needs 63 replicas", "severity": "critical", "recommendations": ["roll back"], '
        '"tools_used": ["made_up_tool"], "confidence": "high"}'
    )
    c = FakeClient([tool_use("get_service_health", {"service": "checkout-api"})], [text("not json")], [text(good)])
    out = s11.run_final_agent(c, "2x?", s6.TOOLS, s7.safe_execute)
    assert out.severity == "critical" and out.tools_used == ["get_service_health"] and out.confidence == "high"


def test_step11_budget_fallback_and_failed_tool_lowers_confidence():
    calls = [tool_use("get_service_health", {"service": "search-api"}, f"t{i}") for i in range(3)]
    out = s11.run_final_agent(FakeClient(calls), "x", s6.TOOLS, s7.safe_execute, max_tool_calls=2)
    assert out.severity == "unknown" and out.confidence == "low"
    good = '{"answer": "a", "severity": "ok", "recommendations": [], "tools_used": [], "confidence": "high"}'
    c = FakeClient([tool_use("get_service_health", {"service": "nope"})], [text(good)])
    assert s11.run_final_agent(c, "x", s6.TOOLS, s7.safe_execute).confidence == "low"
