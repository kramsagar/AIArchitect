import pytest
import responses

from ocp_analyzer.client import AuthError, OCPClient, OCPError, oauth_login
from ocp_analyzer.prometheus import TENANCY_PROXY, PrometheusClient, discover_prometheus

API = "https://api.test:6443"
OAUTH = "https://oauth-openshift.apps.test/oauth/authorize"


def _mock_discovery():
    responses.get(f"{API}/.well-known/oauth-authorization-server", json={"authorization_endpoint": OAUTH})


@responses.activate
def test_oauth_login_returns_token():
    _mock_discovery()
    responses.get(
        OAUTH,
        status=302,
        headers={"Location": "https://oauth/token/implicit#access_token=sha256~abc&expires_in=86400&token_type=Bearer"},
    )
    assert oauth_login(API, "dev", "secret") == "sha256~abc"
    sent = responses.calls[1].request
    assert sent.headers["Authorization"].startswith("Basic ")
    assert sent.headers["X-CSRF-Token"] == "1"
    assert "client_id=openshift-challenging-client" in sent.url


@responses.activate
def test_oauth_login_bad_password():
    _mock_discovery()
    responses.get(OAUTH, status=401)
    with pytest.raises(AuthError, match="invalid username or password"):
        oauth_login(API, "dev", "wrong")


@responses.activate
def test_oauth_login_not_openshift():
    responses.get(f"{API}/.well-known/oauth-authorization-server", status=404)
    with pytest.raises(AuthError, match="OAuth discovery failed"):
        oauth_login(API, "dev", "pw")


@responses.activate
def test_client_requests_and_errors():
    client = OCPClient(API, "tok")
    responses.get(f"{API}/apis/apps/v1/namespaces/shop/deployments", json={"items": [{"metadata": {"name": "a"}}]})
    responses.get(f"{API}/api/v1/namespaces/shop/pods/p1/log", body="line1\nline2")
    responses.get(f"{API}/api/v1/nodes/n1", status=403, json={"message": "nodes is forbidden"})
    assert client.list_deployments("shop")[0]["metadata"]["name"] == "a"
    assert client.get_pod_logs("shop", "p1", "c", 10, previous=True) == "line1\nline2"
    log_req = responses.calls[1].request
    assert "previous=true" in log_req.url and "tailLines=10" in log_req.url
    assert log_req.headers["Authorization"] == "Bearer tok"
    with pytest.raises(OCPError) as exc:
        client.get_node("n1")
    assert exc.value.status == 403


@responses.activate
def test_hpa_falls_back_to_v1():
    client = OCPClient(API, "tok")
    responses.get(f"{API}/apis/autoscaling/v2/namespaces/shop/horizontalpodautoscalers", status=404, json={})
    responses.get(f"{API}/apis/autoscaling/v1/namespaces/shop/horizontalpodautoscalers", json={"items": [{"x": 1}]})
    assert client.list_hpas("shop") == [{"x": 1}]


@responses.activate
def test_prometheus_query_parsing():
    prom = PrometheusClient("https://thanos", token="t")
    responses.get(
        "https://thanos/api/v1/query",
        json={
            "status": "success",
            "data": {"result": [{"metric": {"pod": "a"}, "value": [1, "0.5"]}, {"metric": {}, "value": [1, "NaN"]}]},
        },
    )
    assert prom.query("up") == [{"labels": {"pod": "a"}, "value": 0.5}]


@responses.activate
def test_discovery_prefers_route_then_tenancy():
    kube = OCPClient(API, "tok")
    responses.get(
        f"{API}/apis/route.openshift.io/v1/namespaces/openshift-monitoring/routes/thanos-querier",
        json={"spec": {"host": "thanos.apps.test"}},
    )
    responses.get("https://thanos.apps.test/api/v1/query", status=403, body="forbidden")
    responses.get(f"{API}{TENANCY_PROXY}/api/v1/query", json={"status": "success", "data": {"result": []}})
    prom, notes = discover_prometheus(kube, "shop")
    assert prom is not None and prom.base_url == f"{API}{TENANCY_PROXY}"
    assert prom.namespace == "shop"
    assert "namespace=shop" in responses.calls[-1].request.url
    assert any("unusable" in n for n in notes)
