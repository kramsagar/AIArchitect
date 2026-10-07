"""Prometheus / Thanos Querier client with OpenShift endpoint discovery."""

from __future__ import annotations

import time
from typing import Any

import requests

from .client import OCPClient, OCPError, is_cluster_url

MONITORING_NS = "openshift-monitoring"
TENANCY_PROXY = f"/api/v1/namespaces/{MONITORING_NS}/services/https:thanos-querier:tenancy/proxy"


class PrometheusError(Exception):
    pass


class PrometheusClient:
    """Minimal Prometheus HTTP API client (instant + range queries)."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        verify_tls: bool = True,
        timeout: float = 30,
        namespace: str | None = None,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.namespace = namespace
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.verify = verify_tls
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def _get(self, path: str, params: dict) -> Any:
        if self.namespace:
            params = {**params, "namespace": self.namespace}
        try:
            resp = self.session.get(f"{self.base_url}{path}", params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise PrometheusError(f"Prometheus request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise PrometheusError(f"Prometheus returned {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        if body.get("status") != "success":
            raise PrometheusError(f"Prometheus error: {body.get('error', body)}")
        return body["data"]["result"]

    def query(self, promql: str) -> list[dict]:
        """Instant query -> ``[{"labels": {...}, "value": float}]``."""
        return [
            {"labels": r.get("metric", {}), "value": float(r["value"][1])}
            for r in self._get("/api/v1/query", {"query": promql})
            if r.get("value") and r["value"][1] not in ("NaN", "+Inf", "-Inf")
        ]

    def query_range(
        self, promql: str, minutes: int = 60, step_seconds: int = 60, end: float | None = None
    ) -> list[dict]:
        """Range query -> ``[{"labels": {...}, "values": [[ts, float], ...]}]``."""
        end = end or time.time()
        params = {"query": promql, "start": end - minutes * 60, "end": end, "step": step_seconds}
        out = []
        for r in self._get("/api/v1/query_range", params):
            values = [[float(t), float(v)] for t, v in r.get("values", []) if v not in ("NaN", "+Inf", "-Inf")]
            out.append({"labels": r.get("metric", {}), "values": values})
        return out

    def ping(self) -> bool:
        self.query("vector(1)")
        return True


def discover_prometheus(
    kube: OCPClient, namespace: str, override_url: str | None = None
) -> tuple[PrometheusClient | None, list[str]]:
    """Find a usable query endpoint, from most to least privileged.

    1. user supplied URL
    2. ``thanos-querier`` route in openshift-monitoring (needs cluster-monitoring-view)
    3. tenancy port of thanos-querier through the API service proxy (namespace scoped)
    """
    notes: list[str] = []
    candidates: list[tuple[str, str | None, bool]] = []
    if override_url:
        trusted = is_cluster_url(kube.api_url, override_url)
        if not trusted:
            notes.append(
                f"{override_url} is not an https URL under the cluster domain; querying it without the cluster token."
            )
        candidates.append((override_url, None, trusted))
    else:
        try:
            host = kube.get_route(MONITORING_NS, "thanos-querier")["spec"]["host"]
            candidates.append((f"https://{host}", None, True))
        except (OCPError, KeyError) as exc:
            notes.append(f"thanos-querier route not readable: {exc}")
        candidates.append((f"{kube.api_url}{TENANCY_PROXY}", namespace, True))

    for url, tenancy_ns, send_token in candidates:
        client = PrometheusClient(
            url,
            token=kube.token if send_token else None,
            verify_tls=kube.verify_tls,
            timeout=kube.timeout,
            namespace=tenancy_ns,
        )
        try:
            if tenancy_ns:
                client.query(f'up{{namespace="{namespace}"}}')
            else:
                client.ping()
            return client, notes
        except PrometheusError as exc:
            notes.append(f"Prometheus endpoint {url} unusable: {exc}")
    return None, notes
