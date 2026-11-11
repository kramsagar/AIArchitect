"""The investigator's output contract. Every claim points at evidence, and every evidence item points at a tool call
that actually ran; the agent drops citations it cannot verify (see agent.ground)."""

from __future__ import annotations

from typing import Literal

from m01_agent.schemas import StrictModel
from pydantic import Field

Source = Literal["prometheus", "jaeger", "splunk", "runbook", "changes", "memory"]


class Evidence(StrictModel):
    source: Source
    ref: str = Field(description="Verifiable pointer: PromQL/metric name, trace_id, SPL, runbook chunk id, alert name.")
    finding: str = Field(description="What this evidence shows, with numbers and units.")


class Investigation(StrictModel):
    summary: str = Field(description="2-4 sentence answer for the on-call engineer.")
    status: Literal["healthy", "degraded", "incident", "unknown"]
    affected_services: list[str]
    suspected_cause: str | None = Field(description="Most likely cause, or null if evidence is insufficient.")
    evidence: list[Evidence] = Field(description="Every claim in the summary must be backed by an item here.")
    recommended_actions: list[str] = Field(description="Mitigation first, then diagnosis. Cite runbook steps.")
    runbooks: list[str] = Field(description="Runbook chunk ids used, e.g. runbooks#checkout-latency.")
    confidence: Literal["high", "medium", "low"]
