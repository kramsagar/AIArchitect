"""PromQL used by the collector. All queries are scoped to one namespace and the deployment's pods."""

from __future__ import annotations

LATENCY_BUCKETS = (
    "http_request_duration_seconds_bucket|http_server_requests_seconds_bucket|"
    "http_server_request_duration_seconds_bucket"
)


def pod_regex(pod_names: list[str]) -> str:
    return "|".join(sorted(pod_names))


def instant_queries(namespace: str, pods: list[str], nodes: list[str], rate: str = "5m") -> dict[str, str]:
    pod_re = pod_regex(pods)
    c = f'namespace="{namespace}",pod=~"{pod_re}",container!="",container!="POD"'
    p = f'namespace="{namespace}",pod=~"{pod_re}"'
    queries = {
        "cpu_usage": f"sum by (pod, container) (rate(container_cpu_usage_seconds_total{{{c}}}[{rate}]))",
        "cpu_throttle_ratio": (
            f"sum by (pod, container) (rate(container_cpu_cfs_throttled_periods_total{{{c}}}[{rate}]))"
            f" / sum by (pod, container) (rate(container_cpu_cfs_periods_total{{{c}}}[{rate}]))"
        ),
        "memory_working_set": f"sum by (pod, container) (container_memory_working_set_bytes{{{c}}})",
        "memory_max_1h": (f"max by (pod, container) (max_over_time(container_memory_working_set_bytes{{{c}}}[1h]))"),
        "restarts_1h": (f"sum by (pod, container) (increase(kube_pod_container_status_restarts_total{{{p}}}[1h]))"),
        "net_rx_bytes": f"sum by (pod) (rate(container_network_receive_bytes_total{{{p}}}[{rate}]))",
        "net_tx_bytes": f"sum by (pod) (rate(container_network_transmit_bytes_total{{{p}}}[{rate}]))",
        "net_drops": (
            f"sum by (pod) (rate(container_network_receive_packets_dropped_total{{{p}}}[{rate}])"
            f" + rate(container_network_transmit_packets_dropped_total{{{p}}}[{rate}]))"
        ),
        "http_p95_latency": (
            f'histogram_quantile(0.95, sum by (le) (rate({{__name__=~"{LATENCY_BUCKETS}",{p}}}[{rate}])))'
        ),
    }
    if nodes:
        node_re = "|".join(sorted(nodes))
        queries["node_cpu_util"] = f'instance:node_cpu_utilisation:rate1m{{instance=~"{node_re}"}}'
        queries["node_memory_util"] = f'instance:node_memory_utilisation:ratio{{instance=~"{node_re}"}}'
    return queries


def range_queries(namespace: str, pods: list[str], rate: str = "5m") -> dict[str, str]:
    pod_re = pod_regex(pods)
    c = f'namespace="{namespace}",pod=~"{pod_re}",container!="",container!="POD"'
    p = f'namespace="{namespace}",pod=~"{pod_re}"'
    return {
        "cpu_usage": f"sum by (pod) (rate(container_cpu_usage_seconds_total{{{c}}}[{rate}]))",
        "cpu_throttle_ratio": (
            f"sum by (pod) (rate(container_cpu_cfs_throttled_periods_total{{{c}}}[{rate}]))"
            f" / sum by (pod) (rate(container_cpu_cfs_periods_total{{{c}}}[{rate}]))"
        ),
        "memory_working_set": f"sum by (pod) (container_memory_working_set_bytes{{{c}}})",
        "net_rx_bytes": f"sum by (pod) (rate(container_network_receive_bytes_total{{{p}}}[{rate}]))",
    }
