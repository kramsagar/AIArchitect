"""Collects infra state, logs and metrics for one deployment into a :class:`Snapshot`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from . import queries
from .models import ContainerStats, Snapshot
from .utils import event_time, label_selector, parse_cpu, parse_memory, utcnow


class KubeSource(Protocol):
    def get_deployment(self, namespace: str, name: str) -> dict: ...
    def list_replicasets(self, namespace: str, selector: str = "") -> list[dict]: ...
    def list_pods(self, namespace: str, selector: str = "") -> list[dict]: ...
    def list_events(self, namespace: str) -> list[dict]: ...
    def get_pod_logs(
        self, namespace: str, pod: str, container: str, tail_lines: int = 300, previous: bool = False
    ) -> str: ...
    def list_hpas(self, namespace: str) -> list[dict]: ...
    def get_node(self, name: str) -> dict: ...
    def list_resource_quotas(self, namespace: str) -> list[dict]: ...
    def get_pod_metrics(self, namespace: str) -> list[dict]: ...


class MetricsSource(Protocol):
    base_url: str

    def query(self, promql: str) -> list[dict]: ...
    def query_range(self, promql: str, minutes: int = 60, step_seconds: int = 60) -> list[dict]: ...


@dataclass
class CollectOptions:
    log_tail_lines: int = 300
    max_pods_for_logs: int = 10
    include_previous_logs: bool = True
    lookback_minutes: int = 60
    step_seconds: int = 60
    rate_window: str = "5m"
    max_events: int = 200


Progress = Callable[[str], None]


def _safe(warnings: list[str], label: str, fn: Callable[[], Any], default: Any = None) -> Any:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - collection must be best-effort
        warnings.append(f"{label}: {exc}")
        return default


def collect(
    kube: KubeSource,
    prom: MetricsSource | None,
    namespace: str,
    deployment_name: str,
    options: CollectOptions | None = None,
    progress: Progress | None = None,
) -> Snapshot:
    opts = options or CollectOptions()
    say = progress or (lambda _msg: None)
    warnings: list[str] = []

    say("Reading deployment spec")
    deployment = kube.get_deployment(namespace, deployment_name)
    selector = label_selector(deployment.get("spec", {}).get("selector"))

    say("Listing ReplicaSets and pods")
    replicasets = _safe(warnings, "replicasets", lambda: kube.list_replicasets(namespace, selector), [])
    pods = _safe(warnings, "pods", lambda: kube.list_pods(namespace, selector), [])
    pod_names = [p["metadata"]["name"] for p in pods]

    say("Reading HPA, events and quotas")
    hpa = next(
        (
            h
            for h in _safe(warnings, "hpa", lambda: kube.list_hpas(namespace), [])
            if (h.get("spec", {}).get("scaleTargetRef") or {}).get("name") == deployment_name
        ),
        None,
    )
    related = {deployment_name, *pod_names, *(r["metadata"]["name"] for r in replicasets)}
    if hpa:
        related.add(hpa["metadata"]["name"])
    events = [
        e
        for e in _safe(warnings, "events", lambda: kube.list_events(namespace), [])
        if (e.get("involvedObject") or e.get("regarding") or {}).get("name") in related
    ]
    events.sort(key=lambda e: event_time(e) or utcnow(), reverse=True)
    quotas = _safe(warnings, "resourcequotas", lambda: kube.list_resource_quotas(namespace), [])

    say("Inspecting nodes")
    nodes: dict[str, dict] = {}
    for node_name in sorted({p.get("spec", {}).get("nodeName") for p in pods} - {None}):
        node = _safe(warnings, f"node {node_name}", lambda n=node_name: kube.get_node(n))
        if node:
            nodes[node_name] = node

    say("Fetching container logs")
    logs: dict[str, str] = {}
    for pod in pods[: opts.max_pods_for_logs]:
        name = pod["metadata"]["name"]
        statuses = {s["name"]: s for s in pod.get("status", {}).get("containerStatuses") or []}
        for container in pod.get("spec", {}).get("containers", []):
            cname = container["name"]
            status = statuses.get(cname)
            if not status:
                continue
            if "running" in (status.get("state") or {}) or "terminated" in (status.get("state") or {}):
                text = _safe(
                    warnings,
                    f"logs {name}/{cname}",
                    lambda n=name, c=cname: kube.get_pod_logs(namespace, n, c, opts.log_tail_lines),
                )
                if text:
                    logs[f"{name}/{cname}"] = text
            if opts.include_previous_logs and status.get("restartCount", 0) > 0:
                text = _safe(
                    warnings,
                    f"previous logs {name}/{cname}",
                    lambda n=name, c=cname: kube.get_pod_logs(namespace, n, c, opts.log_tail_lines, True),
                )
                if text:
                    logs[f"{name}/{cname}#previous"] = text

    instant: dict[str, list[dict]] = {}
    series: dict[str, list[dict]] = {}
    metrics_source = "none"
    running = [p["metadata"]["name"] for p in pods if p.get("status", {}).get("phase") == "Running"]
    if prom and pod_names:
        say("Querying Prometheus")
        metrics_source = "prometheus"
        for key, promql in queries.instant_queries(namespace, pod_names, sorted(nodes), opts.rate_window).items():
            instant[key] = _safe(warnings, f"promql {key}", lambda q=promql: prom.query(q), [])
        for key, promql in queries.range_queries(namespace, pod_names, opts.rate_window).items():
            series[key] = _safe(
                warnings,
                f"promql range {key}",
                lambda q=promql: prom.query_range(q, opts.lookback_minutes, opts.step_seconds),
                [],
            )
    elif running:
        say("Prometheus unavailable, falling back to metrics.k8s.io")
        usage = _safe(warnings, "metrics.k8s.io", lambda: kube.get_pod_metrics(namespace), [])
        wanted = set(pod_names)
        cpu, mem = [], []
        for item in usage:
            pod = item["metadata"]["name"]
            if pod not in wanted:
                continue
            for c in item.get("containers", []):
                labels = {"pod": pod, "container": c["name"]}
                cpu.append({"labels": labels, "value": parse_cpu(c["usage"].get("cpu")) or 0.0})
                mem.append({"labels": labels, "value": parse_memory(c["usage"].get("memory")) or 0.0})
        if cpu:
            metrics_source = "metrics-api"
            instant = {"cpu_usage": cpu, "memory_working_set": mem}

    return Snapshot(
        namespace=namespace,
        deployment_name=deployment_name,
        collected_at=utcnow().isoformat(),
        deployment=deployment,
        replicasets=replicasets,
        pods=pods,
        events=events[: opts.max_events],
        hpa=hpa,
        nodes=nodes,
        quotas=quotas,
        logs=logs,
        instant=instant,
        series=series,
        metrics_source=metrics_source,
        prometheus_url=getattr(prom, "base_url", None) if prom else None,
        warnings=warnings,
    )


def _metric_lookup(samples: list[dict]) -> dict[tuple[str, str], float]:
    return {
        (s["labels"].get("pod", ""), s["labels"].get("container", "")): s["value"]
        for s in samples
        if "pod" in s["labels"]
    }


def build_container_stats(snapshot: Snapshot) -> list[ContainerStats]:
    metrics = {key: _metric_lookup(samples) for key, samples in snapshot.instant.items()}
    stats: list[ContainerStats] = []
    for pod in snapshot.pods:
        name = pod["metadata"]["name"]
        status = pod.get("status", {})
        statuses = {s["name"]: s for s in status.get("containerStatuses") or []}
        for container in pod.get("spec", {}).get("containers", []):
            cname = container["name"]
            cs = statuses.get(cname, {})
            state = cs.get("state") or {}
            state_name = next(iter(state), None)
            last = (cs.get("lastState") or {}).get("terminated") or {}
            current_term = state.get("terminated") or {}
            resources = container.get("resources") or {}
            req, lim = resources.get("requests") or {}, resources.get("limits") or {}
            key = (name, cname)

            def m(metric: str, k: tuple[str, str] = key) -> float | None:
                return metrics.get(metric, {}).get(k)

            stats.append(
                ContainerStats(
                    pod=name,
                    container=cname,
                    node=pod.get("spec", {}).get("nodeName"),
                    phase=status.get("phase"),
                    ready=bool(cs.get("ready")),
                    state=state_name,
                    state_reason=(state.get(state_name) or {}).get("reason") if state_name else None,
                    restarts=int(cs.get("restartCount", 0)),
                    last_termination_reason=last.get("reason") or current_term.get("reason"),
                    last_termination_exit_code=last.get("exitCode", current_term.get("exitCode")),
                    cpu_request=parse_cpu(req.get("cpu")),
                    cpu_limit=parse_cpu(lim.get("cpu")),
                    mem_request=parse_memory(req.get("memory")),
                    mem_limit=parse_memory(lim.get("memory")),
                    cpu_usage=m("cpu_usage"),
                    mem_usage=m("memory_working_set"),
                    mem_max=m("memory_max_1h"),
                    throttle_ratio=m("cpu_throttle_ratio"),
                    restarts_1h=m("restarts_1h"),
                )
            )
    return stats
