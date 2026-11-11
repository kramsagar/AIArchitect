"""Backend configuration. Every URL, credential and budget comes from the environment so the same code runs
offline (fixtures), against the Docker lab on your laptop, or against a real cluster."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

FixtureScenario = Literal["checkout-latency", "payments-outage", "healthy"]


def _bool(value: str | None, default: bool) -> bool:
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


class ObsConfig(BaseModel):
    backend: Literal["fixture", "live"] = "fixture"
    scenario: FixtureScenario = "checkout-latency"
    prometheus_url: str = "http://localhost:9090"
    jaeger_url: str = "http://localhost:16686"
    splunk_url: str = "https://localhost:8090"  # Splunk management/REST API (container port 8089)
    splunk_username: str = "admin"
    splunk_password: str = "ShopSphere#Lab1"  # the lab default from lab/docker-compose.yml, not a real secret
    splunk_verify_tls: bool = False  # the lab uses Splunk's self-signed cert; set true with a real CA
    splunk_allowed_indexes: tuple[str, ...] = ("main",)
    shop_url: str = "http://localhost:8080"
    timeout_s: float = Field(5.0, gt=0)
    max_retries: int = Field(2, ge=0)
    cache_ttl_s: float = Field(5.0, ge=0)
    max_rows: int = Field(50, ge=1)  # hard cap on rows/series a tool may return (token budget)
    memory_db: Path = Path.home() / ".m02" / "memory.db"

    @classmethod
    def from_env(cls, **overrides) -> ObsConfig:
        env = {
            "backend": os.getenv("OBS_BACKEND"),
            "scenario": os.getenv("OBS_FIXTURE_SCENARIO"),
            "prometheus_url": os.getenv("PROMETHEUS_URL"),
            "jaeger_url": os.getenv("JAEGER_URL"),
            "splunk_url": os.getenv("SPLUNK_URL"),
            "splunk_username": os.getenv("SPLUNK_USERNAME"),
            "splunk_password": os.getenv("SPLUNK_PASSWORD"),
            "shop_url": os.getenv("SHOP_URL"),
            "timeout_s": os.getenv("OBS_TIMEOUT_S"),
            "memory_db": os.getenv("M02_MEMORY_DB"),
        }
        values = {k: v for k, v in env.items() if v}
        values["splunk_verify_tls"] = _bool(os.getenv("SPLUNK_VERIFY_TLS"), False)
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls.model_validate(values)

    def env(self) -> dict[str, str]:
        """The same config as environment variables, to hand to an MCP server subprocess."""
        return {
            "OBS_BACKEND": self.backend,
            "OBS_FIXTURE_SCENARIO": self.scenario,
            "PROMETHEUS_URL": self.prometheus_url,
            "JAEGER_URL": self.jaeger_url,
            "SPLUNK_URL": self.splunk_url,
            "SPLUNK_USERNAME": self.splunk_username,
            "SPLUNK_PASSWORD": self.splunk_password,
            "SPLUNK_VERIFY_TLS": str(self.splunk_verify_tls).lower(),
            "SHOP_URL": self.shop_url,
            "OBS_TIMEOUT_S": str(self.timeout_s),
        }
