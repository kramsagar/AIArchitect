"""The shared state every agent in the crew reads and writes, and the contracts for the LLM-produced parts.

LangGraph merges each node's returned dict into this state. Plain keys are overwritten (last writer wins); keys
annotated with a *reducer* are combined, which is what makes parallel fan-out safe: four investigators append
evidence at the same time and nothing is lost."""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field


class Evidence(TypedDict):
    id: str  # stable, citable: "alert:<name>", "slo:<svc>", "trace:<id>", "log:<n>", "change:<svc>", runbook chunk id
    source: str  # metrics | traces | logs | changes | runbooks | executor | verifier
    summary: str


def merge_evidence(left: list[Evidence] | None, right: list[Evidence] | None) -> list[Evidence]:
    """Reducer: append, de-duplicated by id (a replayed node must not double the evidence)."""
    out = {e["id"]: e for e in (left or [])}
    for e in right or []:
        out[e["id"]] = e
    return list(out.values())


class IncidentState(TypedDict, total=False):
    alert: str  # what started the run: an alert name or a human's symptom
    severity: Literal["sev1", "sev2", "sev3", "none"]
    focus_service: str | None  # Jaeger/Prometheus service name, e.g. payments-service
    symptom: str
    evidence: Annotated[list[Evidence], merge_evidence]
    timeline: Annotated[list[dict], operator.add]  # {"agent", "event"} in the order things happened
    rca: dict | None
    plan: dict | None
    approval: dict | None
    executed: Annotated[list[str], operator.add]  # idempotency keys of side effects already performed
    verification: dict | None
    attempts: int
    postmortem: str | None
    status: str


class RootCause(BaseModel):
    root_cause: str = Field(min_length=5)
    service: str
    confidence: Literal["high", "medium", "low"]
    evidence_ids: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    action: Literal["reset_faults", "escalate"]  # the ONLY actions the executor knows: an allowlist, not free text
    target: str | None = None  # chaos service name: shop | payments
    rationale: str
    risk: Literal["low", "medium", "high"] = "medium"
    runbook: str | None = None
