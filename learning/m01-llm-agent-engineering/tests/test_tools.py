import json

import pytest

from m01_agent.config import AgentConfig
from m01_agent.errors import ToolError, TransientToolError
from m01_agent.factory import build_registry
from m01_agent.resilience import CircuitBreaker, RetryPolicy, TTLCache, retry_call
from m01_agent.schemas import ServiceHealthArgs, ToolCall
from m01_agent.tools import MockMetricsBackend, assess, evaluate


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("(23 * 7) + sqrt(16)", 165.0),
        ("2^10", 1024.0),
        ("error_budget_minutes(99.9, 30)", 43.2),
        ("burn_rate(0.5, 99.9)", 5.0),
        ("concurrency(5000, 120)", 600.0),
        ("replicas_needed(12000, 800, 30)", 20.0),
        ("parallel_availability(99, 2)", 99.99),
    ],
)
def test_calculator(expr, expected):
    assert evaluate(expr) == pytest.approx(expected, rel=1e-6)


def test_serial_availability():
    assert evaluate("serial_availability(99.9, 99.9)") == pytest.approx(99.8001)


@pytest.mark.parametrize(
    "expr", ["__import__('os').system('id')", "open('/etc/passwd')", "1/0", "2**10000", "a.b", "lambda: 1", "1 +"]
)
def test_calculator_rejects_unsafe_or_invalid(expr):
    with pytest.raises(ToolError):
        evaluate(expr)


def test_health_and_assessment():
    backend = MockMetricsBackend()
    sev = {s: assess(backend(ServiceHealthArgs(service=s)))[0] for s in ("checkout-api", "search-api", "inventory-db")}
    assert sev == {"checkout-api": "critical", "search-api": "ok", "inventory-db": "warning"}
    with pytest.raises(ToolError, match="unknown service"):
        backend(ServiceHealthArgs(service="billing-api"))


def test_strict_schemas():
    for schema in build_registry(AgentConfig()).schemas():
        params = schema["function"]["parameters"]
        assert schema["function"]["strict"] is True
        assert params["additionalProperties"] is False
        assert set(params["required"]) == set(params["properties"])
        assert "default" not in json.dumps(params)


def _call(name, args):
    return ToolCall(id="c", name=name, arguments=args if isinstance(args, str) else json.dumps(args))


def test_registry_converts_failures_to_observations():
    reg = build_registry(AgentConfig())
    assert reg.execute(_call("nope", {})).error_type == "unknown_tool"
    assert reg.execute(_call("get_service_health", '{"service":')).error_type == "invalid_arguments"
    assert reg.execute(_call("get_service_health", {"service": "x", "extra": 1})).error_type == "invalid_arguments"
    assert reg.execute(_call("capacity_calculator", {"expression": "1/0"})).error_type == "tool_error"
    ok = reg.execute(_call("get_service_health", {"service": "checkout-api", "window_minutes": 5}))
    assert ok.ok and ok.output["rps"] == 12400


def test_registry_retries_transient_then_succeeds():
    reg = build_registry(AgentConfig(cache_ttl_s=0), MockMetricsBackend(fail_first_n=2), sleep=lambda s: None)
    obs = reg.execute(_call("get_service_health", {"service": "search-api", "window_minutes": 15}))
    assert obs.ok and obs.attempts == 3


def test_registry_timeout():
    cfg = AgentConfig(tool_timeout_s=0.05, tool_max_retries=0, cache_ttl_s=0)
    reg = build_registry(cfg, MockMetricsBackend(latency_s=0.3))
    obs = reg.execute(_call("get_service_health", {"service": "search-api", "window_minutes": 15}))
    assert not obs.ok and obs.error_type == "timeout"


def test_registry_cache():
    reg = build_registry(AgentConfig(cache_ttl_s=60))
    args = {"service": "search-api", "window_minutes": 15}
    assert not reg.execute(_call("get_service_health", args)).cached
    assert reg.execute(_call("get_service_health", args)).cached


def test_retry_gives_up():
    calls = []

    def boom():
        calls.append(1)
        raise TransientToolError("503")

    with pytest.raises(TransientToolError):
        retry_call(boom, RetryPolicy(max_retries=2), sleep=lambda s: None)
    assert len(calls) == 3


def test_circuit_breaker_opens_and_half_opens():
    now = [0.0]
    cb = CircuitBreaker(failure_threshold=2, reset_timeout_s=10, clock=lambda: now[0])

    def fail():
        raise TransientToolError("x")

    for _ in range(2):
        with pytest.raises(TransientToolError):
            cb.call(fail)
    assert cb.state == "open"
    with pytest.raises(ToolError, match="circuit open"):
        cb.call(lambda: 1)
    now[0] = 11
    assert cb.state == "half_open"
    assert cb.call(lambda: 42) == 42
    assert cb.state == "closed"


def test_ttl_cache_expiry():
    now = [0.0]
    c = TTLCache(ttl_s=5, clock=lambda: now[0])
    c.put("k", 1)
    assert c.get("k") == 1
    now[0] = 6
    assert c.get("k") is None
