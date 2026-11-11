"""Pydantic contracts: tool inputs/outputs, the final structured answer and the run trace."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    # extra="forbid" -> unknown keys are rejected and the JSON schema gets additionalProperties: false.
    model_config = ConfigDict(extra="forbid")


# --- Tool contracts ---------------------------------------------------------------------------


class ServiceHealthArgs(StrictModel):
    service: str = Field(
        min_length=1, max_length=63, description="Service name as registered in the catalog, e.g. 'checkout-api'."
    )
    window_minutes: int = Field(default=15, ge=1, le=1440, description="Look-back window for the metrics.")


class SLO(StrictModel):
    availability_pct: float
    latency_p99_ms: float


class ServiceHealth(StrictModel):
    """Golden signals (latency, traffic, errors, saturation) plus capacity context for one service."""

    service: str
    tier: Literal["tier-0", "tier-1", "tier-2"]
    window_minutes: int
    rps: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    error_rate_pct: float
    cpu_util_pct: float
    saturation_pct: float
    replicas: int
    slo: SLO
    dependencies: dict[str, Literal["healthy", "degraded", "down"]]
    recent_change: str | None
    source: str = "mock-prometheus-v1"


class CapacityCalcArgs(StrictModel):
    expression: str = Field(
        min_length=1,
        max_length=200,
        description="Arithmetic expression using + - * / // % ** and SRE functions: "
        "error_budget_minutes(slo_pct, days), burn_rate(error_rate_pct, slo_pct), concurrency(tps, latency_ms), "
        "replicas_needed(target_tps, tps_per_replica, headroom_pct), serial_availability(a_pct, b_pct, ...), "
        "parallel_availability(pct, n), plus sqrt, ceil, floor, round, min, max, abs, log.",
    )


class CalculationResult(StrictModel):
    expression: str
    result: float


# --- Model <-> runtime messages ------------------------------------------------------------------


class ToolCall(BaseModel):
    """A tool invocation requested by the model. `arguments` is the raw JSON string the model produced."""

    id: str
    name: str
    arguments: str


class Observation(BaseModel):
    """What the runtime feeds back to the model after acting. Errors are data, not exceptions."""

    tool_call_id: str
    tool_name: str
    ok: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    error_type: str | None = None
    attempts: int = 1
    cached: bool = False
    latency_ms: float = 0.0

    def to_model_content(self) -> str:
        if self.ok:
            return self.model_dump_json(include={"ok", "output"})
        return self.model_dump_json(include={"ok", "error", "error_type"})


# --- Final structured answer ---------------------------------------------------------------------

Intent = Literal["service_health", "capacity_planning", "health_and_capacity", "general", "unsupported"]


class AssistantResponse(StrictModel):
    """The contract every final answer must satisfy. Downstream code (UI, paging, audit) relies on it."""

    answer: str = Field(description="Concise answer for an on-call engineer, with the key numbers.")
    intent: Intent = Field(description="What the user asked for.")
    severity: Literal["ok", "warning", "critical", "unknown"] = Field(
        description="ok = within SLO, warning = SLO at risk, critical = SLO breached, "
        "unknown = no service data (e.g. pure capacity math or failed lookups)."
    )
    recommendations: list[str] = Field(description="Concrete, ordered next actions. Empty if none are needed.")
    tools_used: list[str] = Field(description="Names of the tools whose results the answer is based on.")
    confidence: Literal["high", "medium", "low"] = Field(
        description="high if all needed tool calls succeeded, low if any failed or the request was ambiguous."
    )
    follow_up: str | None = Field(description="A clarifying question if the request was ambiguous, else null.")


# --- Run trace ---------------------------------------------------------------------------------


class StepTrace(BaseModel):
    step: int
    decision: Literal["tool_calls", "final", "invalid_output"]
    tool_calls: list[ToolCall] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    note: str | None = None


class Usage(BaseModel):
    llm_calls: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_ms: float = 0.0


RunStatus = Literal["completed", "max_steps", "tool_budget", "timeout", "invalid_output", "llm_error"]


class AgentResult(BaseModel):
    run_id: str
    status: RunStatus
    response: AssistantResponse
    steps: list[StepTrace]
    usage: Usage
