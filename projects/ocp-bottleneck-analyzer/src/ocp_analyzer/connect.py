"""Build kube + metrics sources from user input (live cluster or demo)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .client import OCPClient
from .demo import DemoKube, DemoPrometheus
from .prometheus import discover_prometheus


@dataclass
class Connection:
    kube: Any
    prom: Any | None
    user: str
    demo: bool = False
    notes: list[str] = field(default_factory=list)


def connect(
    api_url: str = "",
    username: str = "",
    password: str = "",
    token: str = "",
    namespace: str = "",
    verify_tls: bool = True,
    prometheus_url: str | None = None,
    demo: bool = False,
) -> Connection:
    if demo:
        return Connection(kube=DemoKube(), prom=DemoPrometheus(), user="demo-user", demo=True)
    if not api_url:
        raise ValueError("Cluster API URL is required")
    if token:
        kube = OCPClient(api_url, token, verify_tls=verify_tls)
    elif username and password:
        kube = OCPClient.login(api_url, username, password, verify_tls=verify_tls)
    else:
        raise ValueError("Provide username + password or a bearer token")
    user = kube.whoami()
    prom, notes = discover_prometheus(kube, namespace, prometheus_url or None)
    if not prom:
        notes.append("No Prometheus endpoint usable; falling back to metrics.k8s.io for CPU/memory only.")
    return Connection(kube=kube, prom=prom, user=user, notes=notes)
