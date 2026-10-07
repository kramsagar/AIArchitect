"""Synthetic OpenShift cluster + Prometheus used by demo mode and tests.

Three deployments in namespace ``shop`` showcase different bottlenecks:

* ``checkout-service`` - CPU throttling, OOMKills, HPA pinned at max, unschedulable pod, DB pool
  exhaustion and slow downstream calls, hot node, quota nearly exhausted.
* ``payment-gateway`` - CrashLoopBackOff caused by a DNS / dependency failure and failing probes.
* ``catalog-service`` - healthy but heavily over-provisioned (cost finding).
"""

from __future__ import annotations

import math
import random
import re
import time
import zlib
from datetime import timedelta
from typing import Any

from .utils import utcnow

DEMO_API_URL = "https://api.demo.ocp.local:6443"
DEMO_NAMESPACE = "shop"
Mi = 2**20


def _ts(minutes_ago: float = 0) -> str:
    return (utcnow() - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resources(cpu_req, mem_req, cpu_lim=None, mem_lim=None) -> dict:
    res: dict[str, dict] = {"requests": {"cpu": cpu_req, "memory": mem_req}}
    limits = {k: v for k, v in (("cpu", cpu_lim), ("memory", mem_lim)) if v}
    if limits:
        res["limits"] = limits
    return res


SCENARIOS: dict[str, dict[str, Any]] = {
    "checkout-service": {
        "image": "quay.io/acme/checkout:2.14.1",
        "replicas": 3,
        "resources": _resources("250m", "256Mi", "500m", "512Mi"),
        "hpa": {"min": 2, "max": 3, "target_cpu": 70, "current_cpu": 168},
        "pods": {
            "checkout-service-7d9f8b6c5d-x2k9p": {
                "node": "worker-1",
                "cpu": 0.49,
                "throttle": 0.47,
                "mem": 431 * Mi,
                "mem_max": 470 * Mi,
                "restarts": 0,
                "rx": 2.1e6,
                "tx": 3.4e6,
            },
            "checkout-service-7d9f8b6c5d-m4qzt": {
                "node": "worker-2",
                "cpu": 0.46,
                "throttle": 0.39,
                "mem": 498 * Mi,
                "mem_max": 511 * Mi,
                "restarts": 6,
                "restarts_1h": 3,
                "last_reason": "OOMKilled",
                "exit_code": 137,
                "rx": 1.9e6,
                "tx": 3.1e6,
                "sawtooth": True,
            },
            "checkout-service-7d9f8b6c5d-r7wbn": {"node": None, "phase": "Pending"},
        },
        "latency_p95": 2.7,
        "logs": "checkout",
    },
    "payment-gateway": {
        "image": "quay.io/acme/payment-gateway:1.8.0",
        "replicas": 1,
        "resources": _resources("100m", "128Mi", "500m", "256Mi"),
        "pods": {
            "payment-gateway-5c6b7d8f9-q8tlm": {
                "node": "worker-3",
                "cpu": 0.02,
                "throttle": 0.0,
                "mem": 61 * Mi,
                "mem_max": 74 * Mi,
                "restarts": 14,
                "restarts_1h": 9,
                "waiting": "CrashLoopBackOff",
                "last_reason": "Error",
                "exit_code": 1,
                "rx": 1.2e4,
                "tx": 0.9e4,
            }
        },
        "latency_p95": None,
        "logs": "payment",
    },
    "catalog-service": {
        "image": "quay.io/acme/catalog:3.2.0",
        "replicas": 2,
        "resources": _resources("1", "1Gi", "2", "2Gi"),
        "pods": {
            "catalog-service-6f7c9d5b4-a1b2c": {
                "node": "worker-2",
                "cpu": 0.06,
                "throttle": 0.0,
                "mem": 141 * Mi,
                "mem_max": 150 * Mi,
                "restarts": 0,
                "rx": 4.0e5,
                "tx": 9.0e5,
            },
            "catalog-service-6f7c9d5b4-d3e4f": {
                "node": "worker-3",
                "cpu": 0.05,
                "throttle": 0.0,
                "mem": 137 * Mi,
                "mem_max": 149 * Mi,
                "restarts": 0,
                "rx": 3.8e5,
                "tx": 8.7e5,
            },
        },
        "latency_p95": 0.08,
        "logs": "catalog",
    },
}

NODES = {
    "worker-1": {"cpu_util": 0.93, "mem_util": 0.71, "pressure": {}},
    "worker-2": {"cpu_util": 0.64, "mem_util": 0.88, "pressure": {"MemoryPressure": "True"}},
    "worker-3": {"cpu_util": 0.31, "mem_util": 0.42, "pressure": {}},
}


def _checkout_logs(pod: str, previous: bool) -> str:
    lines = []
    for i in range(120):
        t = _ts(30 - i * 0.25)
        k = i % 12
        if k == 0:
            lines.append(f"{t} WARN  HikariPool-1 - Connection is not available, request timed out after 30000ms.")
        elif k == 3:
            lines.append(
                f"{t} ERROR o.a.c.OrderController - POST /api/checkout status=503 took {2400 + i * 7}ms "
                f"order={1000 + i}"
            )
        elif k == 5:
            lines.append(f"{t} ERROR c.a.p.PaymentClient - call to payment-gateway:8080 failed: Read timed out")
        elif k == 7:
            lines.append(f"{t} WARN  o.h.e.j.s.SqlExceptionHelper - slow query took {1500 + i * 11}ms")
        elif k == 9 and previous:
            lines.append(f"{t} ERROR java.lang.OutOfMemoryError: Java heap space")
        elif k == 10:
            lines.append(f"{t} INFO  [GC (Allocation Failure) Full GC 498M->471M(512M), 0.81 secs]")
        else:
            lines.append(f"{t} INFO  o.a.c.OrderController - checkout completed order={1000 + i}")
    return "\n".join(lines)


def _payment_logs(pod: str, previous: bool) -> str:
    lines = [f"{_ts(3)} INFO  Starting payment-gateway v1.8.0"]
    for i in range(6):
        lines.append(
            f"{_ts(3 - i * 0.3)} ERROR db: dial tcp: lookup postgres-payments.shop.svc on 172.30.0.10:53: no such host"
        )
        lines.append(f"{_ts(3 - i * 0.3)} WARN  retrying database connection attempt={i + 1}")
    lines.append(f"{_ts(1)} ERROR redis: dial tcp 172.30.12.9:6379: connect: connection refused")
    lines.append(f"{_ts(1)} FATAL could not initialise datastore, exiting")
    return "\n".join(lines)


def _catalog_logs(pod: str, previous: bool) -> str:
    return "\n".join(
        f"{_ts(20 - i * 0.2)} INFO  GET /api/products/{i % 40} status=200 took {12 + i % 9}ms" for i in range(80)
    )


LOGS = {"checkout": _checkout_logs, "payment": _payment_logs, "catalog": _catalog_logs}


class DemoKube:
    """Mimics :class:`ocp_analyzer.client.OCPClient` with synthetic objects."""

    api_url = DEMO_API_URL
    token = "demo-token"
    verify_tls = True
    timeout = 5

    def whoami(self) -> str:
        return "demo-user"

    def list_projects(self) -> list[str]:
        return [DEMO_NAMESPACE]

    def _check_ns(self, namespace: str) -> None:
        if namespace != DEMO_NAMESPACE:
            from .client import OCPError

            raise OCPError(f'namespaces "{namespace}" not found (demo cluster only has "shop")', 404)

    def _deployment(self, name: str) -> dict:
        sc = SCENARIOS[name]
        pods = sc["pods"].values()
        ready = sum(1 for p in pods if p.get("phase", "Running") == "Running" and not p.get("waiting"))
        conditions = [
            {"type": "Available", "status": "True" if ready else "False", "reason": "MinimumReplicasAvailable"},
            {"type": "Progressing", "status": "True", "reason": "NewReplicaSetAvailable"},
        ]
        return {
            "kind": "Deployment",
            "metadata": {"name": name, "namespace": DEMO_NAMESPACE, "labels": {"app": name}},
            "spec": {
                "replicas": sc["replicas"],
                "selector": {"matchLabels": {"app": name}},
                "strategy": {"type": "RollingUpdate"},
                "template": {
                    "metadata": {"labels": {"app": name}},
                    "spec": {"containers": [self._container_spec(name)]},
                },
            },
            "status": {
                "replicas": len(sc["pods"]),
                "readyReplicas": ready,
                "availableReplicas": ready,
                "unavailableReplicas": sc["replicas"] - ready,
                "conditions": conditions,
            },
        }

    def _container_spec(self, name: str) -> dict:
        sc = SCENARIOS[name]
        probe = {"httpGet": {"path": "/health", "port": 8080}, "timeoutSeconds": 1, "periodSeconds": 10}
        return {
            "name": name.split("-")[0],
            "image": sc["image"],
            "resources": sc["resources"],
            "readinessProbe": probe,
            "livenessProbe": probe,
            "env": [{"name": "JAVA_OPTS"}, {"name": "DB_URL"}],
        }

    def list_deployments(self, namespace: str) -> list[dict]:
        self._check_ns(namespace)
        return [self._deployment(n) for n in SCENARIOS]

    def get_deployment(self, namespace: str, name: str) -> dict:
        self._check_ns(namespace)
        if name not in SCENARIOS:
            from .client import OCPError

            raise OCPError(f'deployments.apps "{name}" not found', 404)
        return self._deployment(name)

    def _scenario_for(self, selector: str) -> str | None:
        m = re.search(r"app=([\w-]+)", selector or "")
        return m.group(1) if m and m.group(1) in SCENARIOS else None

    def list_replicasets(self, namespace: str, selector: str = "") -> list[dict]:
        name = self._scenario_for(selector)
        if not name:
            return []
        rs = next(iter(SCENARIOS[name]["pods"])).rsplit("-", 1)[0]
        return [{"metadata": {"name": rs, "labels": {"app": name}}, "spec": {"replicas": SCENARIOS[name]["replicas"]}}]

    def list_pods(self, namespace: str, selector: str = "") -> list[dict]:
        name = self._scenario_for(selector)
        if not name:
            return []
        spec = self._container_spec(name)
        pods = []
        for pod_name, p in SCENARIOS[name]["pods"].items():
            phase = p.get("phase", "Running")
            if phase == "Pending":
                status = {
                    "phase": "Pending",
                    "conditions": [{"type": "PodScheduled", "status": "False", "reason": "Unschedulable"}],
                }
            else:
                waiting = p.get("waiting")
                state = (
                    {"waiting": {"reason": waiting, "message": "back-off 5m0s restarting failed container"}}
                    if waiting
                    else {"running": {"startedAt": _ts(42)}}
                )
                last = (
                    {"terminated": {"reason": p["last_reason"], "exitCode": p["exit_code"], "finishedAt": _ts(4)}}
                    if p.get("last_reason")
                    else {}
                )
                status = {
                    "phase": "Running",
                    "containerStatuses": [
                        {
                            "name": spec["name"],
                            "ready": not waiting,
                            "restartCount": p.get("restarts", 0),
                            "state": state,
                            "lastState": last,
                            "image": spec["image"],
                        }
                    ],
                }
            pods.append(
                {
                    "metadata": {"name": pod_name, "namespace": DEMO_NAMESPACE, "labels": {"app": name}},
                    "spec": {"nodeName": p.get("node"), "containers": [spec]},
                    "status": status,
                }
            )
        return pods

    def list_events(self, namespace: str) -> list[dict]:
        def ev(kind, name, reason, message, count=1, type_="Warning", ago=2):
            return {
                "involvedObject": {"kind": kind, "name": name, "namespace": namespace},
                "reason": reason,
                "message": message,
                "type": type_,
                "count": count,
                "lastTimestamp": _ts(ago),
            }

        return [
            ev(
                "Pod",
                "checkout-service-7d9f8b6c5d-r7wbn",
                "FailedScheduling",
                "0/6 nodes are available: 3 Insufficient cpu, 3 node(s) had untolerated taint "
                "{node-role.kubernetes.io/master: }. preemption: 0/6 nodes are available.",
                count=37,
            ),
            ev(
                "Pod",
                "checkout-service-7d9f8b6c5d-m4qzt",
                "Unhealthy",
                'Readiness probe failed: Get "http://10.128.2.17:8080/health": context deadline exceeded',
                count=23,
            ),
            ev(
                "Pod",
                "checkout-service-7d9f8b6c5d-x2k9p",
                "Unhealthy",
                'Readiness probe failed: Get "http://10.129.0.33:8080/health": context deadline exceeded',
                count=8,
            ),
            ev(
                "HorizontalPodAutoscaler",
                "checkout-service",
                "SuccessfulRescale",
                "New size: 3; reason: cpu resource utilization (percentage of request) above target",
                type_="Normal",
                ago=35,
            ),
            ev(
                "Pod",
                "payment-gateway-5c6b7d8f9-q8tlm",
                "BackOff",
                "Back-off restarting failed container payment in pod payment-gateway-5c6b7d8f9-q8tlm",
                count=61,
            ),
            ev(
                "Pod",
                "payment-gateway-5c6b7d8f9-q8tlm",
                "Unhealthy",
                'Liveness probe failed: Get "http://10.130.1.5:8080/health": dial tcp 10.130.1.5:8080: '
                "connect: connection refused",
                count=12,
            ),
            ev(
                "Pod",
                "catalog-service-6f7c9d5b4-a1b2c",
                "Pulled",
                "Container image already present",
                type_="Normal",
                ago=50,
            ),
        ]

    def get_pod_logs(
        self, namespace: str, pod: str, container: str, tail_lines: int = 300, previous: bool = False
    ) -> str:
        for sc in SCENARIOS.values():
            if pod in sc["pods"]:
                text = LOGS[sc["logs"]](pod, previous)
                return "\n".join(text.splitlines()[-tail_lines:])
        return ""

    def list_hpas(self, namespace: str) -> list[dict]:
        out = []
        for name, sc in SCENARIOS.items():
            h = sc.get("hpa")
            if not h:
                continue
            out.append(
                {
                    "metadata": {"name": name},
                    "spec": {
                        "scaleTargetRef": {"kind": "Deployment", "name": name},
                        "minReplicas": h["min"],
                        "maxReplicas": h["max"],
                        "metrics": [
                            {
                                "type": "Resource",
                                "resource": {
                                    "name": "cpu",
                                    "target": {"type": "Utilization", "averageUtilization": h["target_cpu"]},
                                },
                            }
                        ],
                    },
                    "status": {
                        "currentReplicas": h["max"],
                        "desiredReplicas": h["max"],
                        "currentMetrics": [
                            {
                                "type": "Resource",
                                "resource": {"name": "cpu", "current": {"averageUtilization": h["current_cpu"]}},
                            }
                        ],
                        "conditions": [{"type": "ScalingLimited", "status": "True", "reason": "TooManyReplicas"}],
                    },
                }
            )
        return out

    def get_node(self, name: str) -> dict:
        n = NODES[name]
        conditions = [{"type": "Ready", "status": "True"}] + [
            {"type": t, "status": n["pressure"].get(t, "False")}
            for t in ("MemoryPressure", "DiskPressure", "PIDPressure")
        ]
        return {
            "metadata": {"name": name, "labels": {"node-role.kubernetes.io/worker": ""}},
            "status": {"conditions": conditions, "allocatable": {"cpu": "3500m", "memory": "15Gi", "pods": "250"}},
        }

    def list_resource_quotas(self, namespace: str) -> list[dict]:
        return [
            {
                "metadata": {"name": "shop-quota"},
                "status": {
                    "hard": {"limits.cpu": "6", "limits.memory": "12Gi", "pods": "20"},
                    "used": {"limits.cpu": "5600m", "limits.memory": "7Gi", "pods": "6"},
                },
            }
        ]

    def get_pod_metrics(self, namespace: str) -> list[dict]:
        return []


class DemoPrometheus:
    """Answers the analyzer's PromQL with values from :data:`SCENARIOS`."""

    base_url = "demo://thanos-querier"

    _CONTAINER_METRICS = [
        ("cfs_throttled", "throttle"),
        ("container_cpu_usage", "cpu"),
        ("max_over_time(container_memory", "mem_max"),
        ("container_memory_working_set", "mem"),
        ("restarts_total", "restarts_1h"),
    ]
    _POD_METRICS = [("packets_dropped", "drops"), ("network_receive_bytes", "rx"), ("network_transmit_bytes", "tx")]

    def _pods(self, promql: str) -> list[tuple[str, str, dict, dict]]:
        m = re.search(r'pod=~"([^"]*)"', promql)
        rx = re.compile(m.group(1)) if m else None
        out = []
        for dep, sc in SCENARIOS.items():
            for pod, p in sc["pods"].items():
                if p.get("phase") == "Pending" or (rx and not rx.fullmatch(pod)):
                    continue
                out.append((dep, pod, p, sc))
        return out

    def _samples(self, promql: str) -> list[tuple[dict, float, dict]]:
        if "vector(1)" in promql or promql.startswith("up"):
            return [({}, 1.0, {})]
        if "histogram_quantile" in promql:
            deps = {d for d, *_ in self._pods(promql)}
            vals = [SCENARIOS[d]["latency_p95"] for d in deps if SCENARIOS[d]["latency_p95"] is not None]
            return [({}, max(vals), {})] if vals else []
        for needle, key in (("node_cpu_utilisation", "cpu_util"), ("node_memory_utilisation", "mem_util")):
            if needle in promql:
                m = re.search(r'instance=~"([^"]*)"', promql)
                rx = re.compile(m.group(1)) if m else None
                return [({"instance": n}, v[key], {}) for n, v in NODES.items() if not rx or rx.fullmatch(n)]
        by_pod_only = "by (pod)" in promql
        for needle, key in self._CONTAINER_METRICS:
            if needle in promql:
                rows = []
                for dep, pod, p, _sc in self._pods(promql):
                    labels = {"pod": pod} if by_pod_only else {"pod": pod, "container": dep.split("-")[0]}
                    rows.append((labels, float(p.get(key, 0.0)), p))
                return rows
        for needle, key in self._POD_METRICS:
            if needle in promql:
                return [({"pod": pod}, float(p.get(key, 0.0)), p) for _d, pod, p, _s in self._pods(promql)]
        return []

    def query(self, promql: str) -> list[dict]:
        return [{"labels": labels, "value": value} for labels, value, _ in self._samples(promql)]

    def query_range(self, promql: str, minutes: int = 60, step_seconds: int = 60) -> list[dict]:
        end = time.time()
        steps = max(2, minutes * 60 // step_seconds)
        out = []
        for labels, value, p in self._samples(promql):
            rng = random.Random(zlib.crc32(f"{labels}{promql[:40]}".encode()))
            values = []
            for i in range(steps):
                ts = end - (steps - 1 - i) * step_seconds
                if p.get("sawtooth") and "memory" in promql:
                    v = (p["mem_max"] * 0.55) + (p["mem_max"] * 0.45) * ((i % 18) / 17)
                else:
                    ramp = 0.6 + 0.4 * (i / steps)
                    v = value * ramp * (1 + 0.12 * math.sin(i / 5) + rng.uniform(-0.05, 0.05))
                values.append([ts, max(v, 0.0)])
            out.append({"labels": labels, "values": values})
        return out
