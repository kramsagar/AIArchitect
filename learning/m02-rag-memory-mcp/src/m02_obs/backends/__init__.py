"""Backends the MCP server exposes. `build_backends` returns live HTTP clients or offline fixtures, same interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import ObsConfig
from .chaos import ChangeBackend
from .fixtures import FixtureBackends
from .http import BackendClient
from .jaeger import JaegerBackend
from .prometheus import PrometheusBackend
from .splunk import SplunkBackend


@dataclass
class Backends:
    metrics: Any  # .query .slo_status .alerts
    traces: Any  # .services .search .get_trace
    logs: Any  # .search(spl, earliest_minutes, limit)
    changes: Any  # .recent_changes
    mode: str


class _FixtureLogs:
    def __init__(self, fx: FixtureBackends) -> None:
        self.search = fx.log_search


def build_backends(config: ObsConfig) -> Backends:
    if config.backend == "fixture":
        fx = FixtureBackends(config.scenario)
        return Backends(metrics=fx, traces=fx, logs=_FixtureLogs(fx), changes=fx, mode=f"fixture:{config.scenario}")

    def client(name: str, url: str, **kw) -> BackendClient:
        return BackendClient(name, url, timeout_s=config.timeout_s, max_retries=config.max_retries, **kw)

    return Backends(
        metrics=PrometheusBackend(
            client("prometheus", config.prometheus_url, cache_ttl_s=config.cache_ttl_s), config.max_rows
        ),
        traces=JaegerBackend(client("jaeger", config.jaeger_url), config.max_rows),
        logs=SplunkBackend(
            client(
                "splunk",
                config.splunk_url,
                auth=(config.splunk_username, config.splunk_password),
                verify=config.splunk_verify_tls,
            ),
            config.splunk_allowed_indexes,
            config.max_rows,
        ),
        changes=ChangeBackend(client("shopsphere", config.shop_url)),
        mode="live",
    )
