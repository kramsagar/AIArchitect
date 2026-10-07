"""Thin, read-only OpenShift / Kubernetes REST client with OpenShift OAuth login."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
import urllib3

CHALLENGING_CLIENT = "openshift-challenging-client"


class OCPError(Exception):
    """Raised when the API server returns an error."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class AuthError(OCPError):
    """Raised when authentication fails."""


def _session(verify_tls: bool) -> requests.Session:
    session = requests.Session()
    session.verify = verify_tls
    if not verify_tls:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return session


def oauth_login(api_url: str, username: str, password: str, verify_tls: bool = True, timeout: float = 30) -> str:
    """Exchange username/password for an OAuth bearer token (same flow as ``oc login -u -p``)."""
    api_url = api_url.rstrip("/")
    session = _session(verify_tls)
    try:
        meta = session.get(f"{api_url}/.well-known/oauth-authorization-server", timeout=timeout)
    except requests.RequestException as exc:
        raise AuthError(f"Cannot reach API server {api_url}: {exc}") from exc
    if meta.status_code != 200:
        raise AuthError(f"OAuth discovery failed ({meta.status_code}); is this an OpenShift API URL?", meta.status_code)
    authorize = meta.json().get("authorization_endpoint")
    if not authorize:
        raise AuthError("OAuth metadata does not contain an authorization_endpoint")

    try:
        resp = session.get(
            authorize,
            params={"client_id": CHALLENGING_CLIENT, "response_type": "token"},
            auth=(username, password),
            headers={"X-CSRF-Token": "1"},
            allow_redirects=False,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise AuthError(f"Cannot reach OAuth server: {exc}") from exc
    if resp.status_code == 401:
        raise AuthError("Login failed: invalid username or password", 401)

    location = resp.headers.get("Location", "")
    parsed = urlparse(location)
    fragment = parse_qs(parsed.fragment)
    if "access_token" in fragment:
        return fragment["access_token"][0]
    query = parse_qs(parsed.query)
    error = (query.get("error_description") or query.get("error") or [f"HTTP {resp.status_code}"])[0]
    raise AuthError(f"Login failed: {error}", resp.status_code)


class OCPClient:
    """Read-only client for the subset of the Kubernetes/OpenShift API used by the analyzer."""

    def __init__(
        self,
        api_url: str,
        token: str,
        verify_tls: bool = True,
        timeout: float = 30,
        session: requests.Session | None = None,
    ):
        self.api_url = api_url.rstrip("/")
        self.token = token
        self.verify_tls = verify_tls
        self.timeout = timeout
        self.session = session or _session(verify_tls)
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.session.headers["Accept"] = "application/json"

    @classmethod
    def login(
        cls, api_url: str, username: str, password: str, verify_tls: bool = True, timeout: float = 30
    ) -> OCPClient:
        token = oauth_login(api_url, username, password, verify_tls=verify_tls, timeout=timeout)
        return cls(api_url, token, verify_tls=verify_tls, timeout=timeout)

    def _request(self, path: str, params: dict | None = None, as_text: bool = False) -> Any:
        url = f"{self.api_url}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise OCPError(f"GET {path} failed: {exc}") from exc
        if resp.status_code == 401:
            raise AuthError("Token rejected by API server (expired or invalid)", 401)
        if resp.status_code >= 400:
            try:
                message = resp.json().get("message", resp.text)
            except ValueError:
                message = resp.text
            raise OCPError(f"GET {path} -> {resp.status_code}: {message[:300]}", resp.status_code)
        return resp.text if as_text else resp.json()

    def _items(self, path: str, params: dict | None = None) -> list[dict]:
        return self._request(path, params=params).get("items", [])

    # identity / projects -------------------------------------------------------------------
    def whoami(self) -> str:
        try:
            return self._request("/apis/user.openshift.io/v1/users/~")["metadata"]["name"]
        except OCPError:
            return "unknown"

    def list_projects(self) -> list[str]:
        try:
            items = self._items("/apis/project.openshift.io/v1/projects")
        except OCPError:
            items = self._items("/api/v1/namespaces")
        return sorted(i["metadata"]["name"] for i in items)

    # workloads -------------------------------------------------------------------------------
    def list_deployments(self, namespace: str) -> list[dict]:
        return self._items(f"/apis/apps/v1/namespaces/{namespace}/deployments")

    def get_deployment(self, namespace: str, name: str) -> dict:
        return self._request(f"/apis/apps/v1/namespaces/{namespace}/deployments/{name}")

    def list_replicasets(self, namespace: str, selector: str = "") -> list[dict]:
        return self._items(f"/apis/apps/v1/namespaces/{namespace}/replicasets", {"labelSelector": selector})

    def list_pods(self, namespace: str, selector: str = "") -> list[dict]:
        return self._items(f"/api/v1/namespaces/{namespace}/pods", {"labelSelector": selector})

    def list_events(self, namespace: str) -> list[dict]:
        return self._items(f"/api/v1/namespaces/{namespace}/events")

    def get_pod_logs(
        self, namespace: str, pod: str, container: str, tail_lines: int = 300, previous: bool = False
    ) -> str:
        params = {"container": container, "tailLines": tail_lines, "timestamps": "true"}
        if previous:
            params["previous"] = "true"
        return self._request(f"/api/v1/namespaces/{namespace}/pods/{pod}/log", params, as_text=True)

    def list_hpas(self, namespace: str) -> list[dict]:
        try:
            return self._items(f"/apis/autoscaling/v2/namespaces/{namespace}/horizontalpodautoscalers")
        except OCPError as exc:
            if exc.status != 404:
                raise
            return self._items(f"/apis/autoscaling/v1/namespaces/{namespace}/horizontalpodautoscalers")

    def get_node(self, name: str) -> dict:
        return self._request(f"/api/v1/nodes/{name}")

    def list_resource_quotas(self, namespace: str) -> list[dict]:
        return self._items(f"/api/v1/namespaces/{namespace}/resourcequotas")

    def get_pod_metrics(self, namespace: str) -> list[dict]:
        return self._items(f"/apis/metrics.k8s.io/v1beta1/namespaces/{namespace}/pods")

    def get_route(self, namespace: str, name: str) -> dict:
        return self._request(f"/apis/route.openshift.io/v1/namespaces/{namespace}/routes/{name}")
