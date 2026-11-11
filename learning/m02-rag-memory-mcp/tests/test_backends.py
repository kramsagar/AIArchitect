import httpx
import pytest
from m01_agent.errors import ToolError

from m02_obs.backends import build_backends
from m02_obs.backends.http import BackendClient
from m02_obs.backends.jaeger import summarize_trace
from m02_obs.backends.prometheus import PrometheusBackend
from m02_obs.backends.splunk import validate_spl
from m02_obs.config import ObsConfig


def client(handler, **kw) -> BackendClient:
    return BackendClient("test", "http://backend", transport=httpx.MockTransport(handler), sleep=lambda s: None, **kw)


def test_retries_transient_then_succeeds():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(503) if len(calls) < 2 else httpx.Response(200, json={"ok": True})

    assert client(handler).get_json("/x") == {"ok": True}
    assert len(calls) == 2


def test_auth_error_is_not_retried():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(401)

    with pytest.raises(ToolError, match="authentication"):
        client(handler).get_json("/x")
    assert len(calls) == 1


def test_ttl_cache_absorbs_repeat_calls():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"n": len(calls)})

    c = client(handler, cache_ttl_s=60)
    assert c.get_json("/x") == c.get_json("/x") == {"n": 1}


def test_prometheus_query_shapes_and_caps_series():
    def handler(req):
        result = [{"metric": {"service_name": f"s{i}"}, "value": [0, "0.25"]} for i in range(5)]
        return httpx.Response(200, json={"status": "success", "data": {"resultType": "vector", "result": result}})

    out = PrometheusBackend(client(handler), max_rows=3).query("up")
    assert len(out["series"]) == 3
    assert out["series"][0]["value"] == 0.25
    with pytest.raises(ToolError):
        PrometheusBackend(client(handler)).query("  ")


@pytest.mark.parametrize(
    "spl",
    [
        "index=main | delete",
        "index=main | outputlookup x.csv",
        "index=main | rest /services/server/info",
        "index=_internal error",
        "error | stats count",
        "| makeresults",
        "index=main `evil_macro`",
        "",
    ],
)
def test_spl_guardrail_rejects_unsafe_searches(spl):
    with pytest.raises(ToolError):
        validate_spl(spl, ("main",))


def test_spl_guardrail_allows_read_only_search():
    safe = validate_spl("index=main otel.log.severity.text=ERROR | stats count by service.name", ("main",))
    assert safe.startswith("search index=main")


@pytest.mark.parametrize("scenario", ["healthy", "checkout-latency", "payments-outage"])
def test_fixtures_match_live_shapes(scenario):
    be = build_backends(ObsConfig(scenario=scenario))
    slo = be.metrics.slo_status()
    assert {"shopsphere-shop", "payments-service"} <= set(slo["services"])
    assert set(be.metrics.alerts()) == {"firing", "pending"}
    assert "any_active" in be.changes.recent_changes()
    traces = be.traces.search("shopsphere-shop", "POST /api/checkout")
    if scenario != "healthy":
        t = be.traces.get_trace(traces["traces"][0]["trace_id"])
        assert {"trace_id", "duration_ms", "services", "error_spans", "slowest_spans"} <= set(t)
    with pytest.raises(ToolError):
        be.logs.search("index=main | delete")


def test_trace_summary_finds_cross_service_bottleneck():
    be = build_backends(ObsConfig(scenario="checkout-latency"))
    tid = be.traces.search("shopsphere-shop", "POST /api/checkout")["traces"][0]["trace_id"]
    t = be.traces.get_trace(tid)
    assert "payments-service" in t["services"]
    assert any(s["operation"] == "payment-provider.authorize" and s["ms"] > 1000 for s in t["slowest_spans"])
    assert summarize_trace  # exported for reuse in M3
