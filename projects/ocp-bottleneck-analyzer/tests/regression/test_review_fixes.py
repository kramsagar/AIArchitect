import copy

import pytest
import responses

from ocp_analyzer.agent import BottleneckAgent, LLMConfig, promql_scope_error
from ocp_analyzer.analyzer import run_analysis
from ocp_analyzer.client import AuthError, OCPClient, is_cluster_url, oauth_login
from ocp_analyzer.collector import collect
from ocp_analyzer.prometheus import discover_prometheus
from ocp_analyzer.utils import redact

API = "https://api.c1.example.com:6443"


def _ids(report):
    return {f.rule_id for f in report.findings}


def test_is_cluster_url():
    assert is_cluster_url(API, "https://oauth-openshift.apps.c1.example.com/oauth/authorize")
    assert is_cluster_url(API, "https://api.c1.example.com:6443/x")
    assert not is_cluster_url(API, "http://oauth-openshift.apps.c1.example.com/oauth/authorize")
    assert not is_cluster_url(API, "https://evil.example.net/oauth/authorize")
    assert not is_cluster_url(API, "https://c1.example.com.evil.net/")


@responses.activate
def test_oauth_refuses_foreign_authorize_endpoint():
    responses.get(
        f"{API}/.well-known/oauth-authorization-server",
        json={"authorization_endpoint": "https://evil.example.net/oauth/authorize"},
    )
    with pytest.raises(AuthError, match="Refusing to send credentials"):
        oauth_login(API, "dev", "secret")
    assert len(responses.calls) == 1


@responses.activate
def test_prometheus_override_outside_cluster_gets_no_token():
    kube = OCPClient(API, "sha256~clustertoken")
    responses.get("http://prom.other.net/api/v1/query", json={"status": "success", "data": {"result": []}})
    prom, notes = discover_prometheus(kube, "shop", "http://prom.other.net")
    assert prom is not None
    assert "Authorization" not in responses.calls[0].request.headers
    assert any("without the cluster token" in n for n in notes)


@responses.activate
def test_prometheus_override_in_cluster_gets_token():
    kube = OCPClient(API, "tok")
    url = "https://thanos.apps.c1.example.com"
    responses.get(f"{url}/api/v1/query", json={"status": "success", "data": {"result": []}})
    prom, _ = discover_prometheus(kube, "shop", url)
    assert prom is not None
    assert responses.calls[0].request.headers["Authorization"] == "Bearer tok"


def _patch_hpa(kube, fn):
    original = kube.list_hpas

    def patched(ns):
        items = copy.deepcopy(original(ns))
        for h in items:
            fn(h)
        return items

    kube.list_hpas = patched


def test_hpa_at_max_but_idle_is_not_a_bottleneck(kube, prom):
    def idle(h):
        h["status"]["conditions"] = []
        for m in h["status"].get("currentMetrics") or []:
            m["resource"]["current"]["averageUtilization"] = 10

    _patch_hpa(kube, idle)
    assert "hpa_at_max" not in _ids(run_analysis(kube, prom, "shop", "checkout-service"))


def test_hpa_for_other_kind_is_ignored(kube, prom):
    _patch_hpa(kube, lambda h: h["spec"]["scaleTargetRef"].update(kind="StatefulSet"))
    assert collect(kube, prom, "shop", "checkout-service").hpa is None


def test_scheduled_pending_pod_reported_as_initializing(kube, prom):
    original = kube.list_pods

    def pods(ns, selector=""):
        items = copy.deepcopy(original(ns, selector))
        for p in items:
            if p["status"].get("phase") == "Pending":
                p["spec"]["nodeName"] = "worker-1"
                p["status"]["initContainerStatuses"] = [
                    {"name": "migrate", "state": {"waiting": {"reason": "PodInitializing"}}}
                ]
        return items

    kube.list_pods = pods
    kube.list_events = lambda ns: []
    ids = _ids(run_analysis(kube, prom, "shop", "checkout-service"))
    assert "pod_initializing" in ids and "pending_pod" not in ids


def test_metrics_api_fills_gaps_when_prometheus_is_empty(kube, prom):
    original = prom.query
    prom.query = lambda q: [] if "container_cpu_usage" in q or "container_memory_working_set" in q else original(q)
    kube.get_pod_metrics = lambda ns: [
        {
            "metadata": {"name": "catalog-service-6f7c9d5b4-a1b2c"},
            "containers": [{"name": "catalog", "usage": {"cpu": "50m", "memory": "100Mi"}}],
        }
    ]
    snap = collect(kube, prom, "shop", "catalog-service")
    assert snap.metrics_source == "prometheus+metrics-api"
    assert snap.instant["cpu_usage"][0]["value"] == 0.05
    assert any("metrics.k8s.io" in w for w in snap.warnings)


@pytest.mark.parametrize(
    "query",
    [
        'sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="shop", container!=""}[5m]))',
        'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{namespace="shop"}[5m])))',
        'kube_pod_info{namespace="shop"} * on(pod) group_left(node) kube_pod_status_ready{namespace="shop"} > 0.5',
        'max_over_time(container_memory_working_set_bytes{namespace="shop"}[1h:1m]) offset 5m',
    ],
)
def test_promql_scope_allows_namespaced_queries(query):
    assert promql_scope_error(query, "shop") is None


@pytest.mark.parametrize(
    "query",
    [
        "up",
        "sum(rate(container_cpu_usage_seconds_total[5m]))",
        'container_memory_working_set_bytes{namespace="kube-system"}',
        'container_memory_working_set_bytes{namespace=~"shop|kube-system"}',
        'container_memory_working_set_bytes{namespace="shop", namespace!="x"}',
        'up{namespace="shop"} or node_memory_MemAvailable_bytes',
        'up{job="x"}',
    ],
)
def test_promql_scope_rejects_other_namespaces(query):
    assert promql_scope_error(query, "shop")


def test_agent_run_promql_enforces_scope(kube, prom):
    snap = collect(kube, prom, "shop", "checkout-service")
    agent = BottleneckAgent(LLMConfig(api_key="x"), snap, [], [], [], prom=prom, client=object())
    assert "rejected" in agent.run_promql("up")["error"]
    assert isinstance(agent.run_promql('up{namespace="shop"}'), list)


def test_redact_masks_secrets():
    out = redact(
        {
            "grep": "password=hunter2 Authorization: Bearer abcdefghijkl token: sha256~" + "x" * 30,
            "items": ["api_key='sk-" + "a" * 20 + "'", 3],
        }
    )
    text = str(out)
    assert "hunter2" not in text and "abcdefghijkl" not in text and "sk-aaaa" not in text and "x" * 30 not in text
    assert out["items"][1] == 3
