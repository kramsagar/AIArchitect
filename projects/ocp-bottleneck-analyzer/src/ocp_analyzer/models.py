"""Data models shared by collectors, rules, the agent and the UI."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def weight(self) -> int:
        return {"critical": 25, "high": 12, "medium": 5, "low": 2, "info": 0}[self.value]

    @property
    def rank(self) -> int:
        return {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}[self.value]


class Finding(BaseModel):
    rule_id: str
    title: str
    severity: Severity
    category: str
    resource: str
    description: str
    evidence: list[str] = Field(default_factory=list)
    recommendation: str = ""


class ContainerStats(BaseModel):
    """Spec + status + live metrics for one container of one pod."""

    pod: str
    container: str
    node: str | None = None
    phase: str | None = None
    ready: bool = False
    state: str | None = None
    state_reason: str | None = None
    restarts: int = 0
    last_termination_reason: str | None = None
    last_termination_exit_code: int | None = None
    cpu_request: float | None = None
    cpu_limit: float | None = None
    mem_request: float | None = None
    mem_limit: float | None = None
    cpu_usage: float | None = None
    mem_usage: float | None = None
    mem_max: float | None = None
    throttle_ratio: float | None = None
    restarts_1h: float | None = None

    @staticmethod
    def _ratio(a: float | None, b: float | None) -> float | None:
        return a / b if a is not None and b else None

    @property
    def cpu_limit_util(self) -> float | None:
        return self._ratio(self.cpu_usage, self.cpu_limit)

    @property
    def cpu_request_util(self) -> float | None:
        return self._ratio(self.cpu_usage, self.cpu_request)

    @property
    def mem_limit_util(self) -> float | None:
        peak = max(v for v in (self.mem_usage, self.mem_max, 0.0) if v is not None)
        return self._ratio(peak or None, self.mem_limit)

    @property
    def mem_request_util(self) -> float | None:
        return self._ratio(self.mem_usage, self.mem_request)


class LogInsight(BaseModel):
    pod: str
    container: str
    previous: bool = False
    lines: int = 0
    category_counts: dict[str, int] = Field(default_factory=dict)
    samples: dict[str, list[str]] = Field(default_factory=dict)
    top_templates: list[dict[str, Any]] = Field(default_factory=list)


class Snapshot(BaseModel):
    """Everything collected from the cluster for one deployment."""

    namespace: str
    deployment_name: str
    collected_at: str
    deployment: dict[str, Any]
    replicasets: list[dict[str, Any]] = Field(default_factory=list)
    pods: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    hpa: dict[str, Any] | None = None
    nodes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    quotas: list[dict[str, Any]] = Field(default_factory=list)
    logs: dict[str, str] = Field(default_factory=dict)
    instant: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    series: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    metrics_source: str = "none"
    prometheus_url: str | None = None
    warnings: list[str] = Field(default_factory=list)


class AgentStep(BaseModel):
    step: int
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_preview: str = ""


class AnalysisReport(BaseModel):
    snapshot: Snapshot
    containers: list[ContainerStats]
    findings: list[Finding]
    log_insights: list[LogInsight]
    health_score: int
    summary_markdown: str
    summary_source: str = "rules"
    llm_model: str | None = None
    agent_trace: list[AgentStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def severity_counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for f in self.findings:
            counts[f.severity.value] += 1
        return counts
