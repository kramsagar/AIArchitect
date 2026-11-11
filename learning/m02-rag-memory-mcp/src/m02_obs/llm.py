"""LLMs for the investigator. Claude reuses the M1 adapter with the Investigation schema as its structured output;
the mock is a deterministic policy that follows the same procedure, so the whole MCP loop runs offline."""

from __future__ import annotations

import json
import re
from typing import Any

from m01_agent.config import AgentConfig
from m01_agent.jsonschema import strict_json_schema
from m01_agent.llm.anthropic_llm import AnthropicLLM, transform_schema
from m01_agent.llm.base import LLMDecision
from m01_agent.schemas import ToolCall

from .schemas import Evidence, Investigation


class ClaudeInvestigatorLLM(AnthropicLLM):
    def __init__(self, config: AgentConfig, client: Any | None = None) -> None:
        super().__init__(config, client)
        self.output_format = {"type": "json_schema", "schema": transform_schema(strict_json_schema(Investigation))}


def _observations(messages: list[dict[str, Any]]) -> list[tuple[str, dict, dict]]:
    """(tool name, args, parsed result) for every tool result in the conversation so far."""
    calls = {}
    for m in messages:
        for c in m.get("tool_calls") or []:
            calls[c["id"]] = (c["function"]["name"], json.loads(c["function"]["arguments"] or "{}"))
    out = []
    for m in messages:
        if m["role"] == "tool" and m["tool_call_id"] in calls:
            name, args = calls[m["tool_call_id"]]
            out.append((name, args, json.loads(m["content"])))
    return out


class MockInvestigatorLLM:
    """Scripted investigator: broad -> runbook + traces -> one trace + its logs -> grounded final answer."""

    def __init__(self) -> None:
        self._n = 0

    def _calls(self, *calls: tuple[str, dict]) -> LLMDecision:
        out = []
        for name, args in calls:
            self._n += 1
            out.append(ToolCall(id=f"mock_{self._n}", name=name, arguments=json.dumps(args)))
        return LLMDecision(tool_calls=out, prompt_tokens=0, completion_tokens=0)

    def decide(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, timeout_s: float) -> LLMDecision:
        obs = _observations(messages)
        ran = {name for name, _, _ in obs}
        out = {name: r.get("output") for name, _, r in obs if r.get("ok")}
        if "get_slo_status" not in ran:
            return self._calls(("get_slo_status", {}), ("list_firing_alerts", {}), ("get_recent_changes", {}))
        focus, svc = self._focus(out.get("get_slo_status") or {})
        alerts = [a["alert"] for a in (out.get("list_firing_alerts") or {}).get("firing", [])]
        if focus != "healthy" and "search_traces" not in ran:
            symptom = "checkout latency slow" if focus == "latency" else "error budget burn 5xx errors"
            query = " ".join([*alerts, symptom])
            trace_args = {"service": "shopsphere-shop", "operation": "POST /api/checkout", "limit": 3}
            trace_args.update({"min_duration_ms": 1000} if focus == "latency" else {"errors_only": True})
            if focus == "errors" and svc != "shopsphere-shop":
                trace_args = {"service": svc, "errors_only": True, "limit": 3}
            return self._calls(("search_runbooks", {"query": query, "k": 2}), ("search_traces", trace_args))
        traces = (out.get("search_traces") or {}).get("traces") or []
        if traces and "get_trace" not in ran:
            tid = traces[0]["trace_id"]
            return self._calls(
                ("get_trace", {"trace_id": tid}), ("search_logs", {"query": f"index=main trace_id={tid}"})
            )
        return self._final(focus, svc, out, alerts, messages)

    @staticmethod
    def _focus(slo: dict) -> tuple[str, str]:
        services = slo.get("services", {})
        burn = {s: v.get("burn_rate_1h") or 0 for s, v in services.items()}
        err = {s: v.get("error_ratio_5m") or 0 for s, v in services.items()}
        worst = max(services, key=lambda s: (err[s], burn[s]), default="shopsphere-shop")
        if services and (err[worst] > 0.01 or burn[worst] >= 1):
            return "errors", worst
        slow = slo.get("checkout_slow_ratio_5m") or 0
        if slow > 0.05 or any((v.get("p95_ms") or 0) > 1000 for v in services.values()):
            return "latency", "shopsphere-shop"
        return "healthy", worst

    def _final(self, focus: str, svc: str, out: dict, alerts: list[str], messages: list[dict[str, Any]]) -> LLMDecision:
        slo = out.get("get_slo_status") or {}
        changes = (out.get("get_recent_changes") or {}).get("active_faults") or {}
        runbooks = [r["id"] for r in (out.get("search_runbooks") or {}).get("results", [])]
        trace = out.get("get_trace")
        logs = (out.get("search_logs") or {}).get("results") or []
        ev: list[Evidence] = []
        for name, v in slo.get("services", {}).items():
            ev.append(
                Evidence(
                    source="prometheus",
                    ref="shopsphere:http_latency_seconds:p95_5m",
                    finding=f"{name}: p95 {v.get('p95_ms')} ms, 5m error ratio {_pct(v.get('error_ratio_5m'))}, "
                    f"burn rate {v.get('burn_rate_1h')}x",
                )
            )
        for a in alerts:
            ev.append(Evidence(source="prometheus", ref=a, finding=f"alert {a} is firing"))
        if changes:
            ev.append(
                Evidence(source="changes", ref="get_recent_changes", finding=f"active changes: {json.dumps(changes)}")
            )
        affected = sorted(
            {
                n
                for n, v in slo.get("services", {}).items()
                if (v.get("p95_ms") or 0) > 1000 or (v.get("error_ratio_5m") or 0) > 0.01
            }
        )
        cause, actions = None, []
        if focus == "healthy":
            summary = "No active incident: every service is inside its SLO and no alerts are firing."
            status, confidence = "healthy", "high"
        else:
            if trace:
                culprit = self._culprit(trace, focus)
                cause = (
                    f"{culprit['service']} {culprit['operation']} takes {culprit['ms']} ms of a "
                    f"{trace['duration_ms']} ms checkout"
                    if focus == "latency"
                    else f"{culprit['service']} {culprit['operation']} failing ({culprit.get('error', 'error')})"
                )
                ev.append(Evidence(source="jaeger", ref=trace["trace_id"], finding=cause))
                affected = sorted(set(affected) | set(trace["services"]))
            for row in logs[:2]:
                ev.append(
                    Evidence(
                        source="splunk",
                        ref=f"index=main trace_id={row.get('trace_id')}",
                        finding=f"{row.get('service.name')} {row.get('otel.log.severity.text')}: {row.get('_raw')}",
                    )
                )
            if changes:
                cause = (cause + "; " if cause else "") + f"coincides with active change {json.dumps(changes)}"
            for rid in runbooks[:2]:
                ev.append(Evidence(source="runbook", ref=rid, finding=f"procedure for this symptom: {rid}"))
            if focus == "latency":
                actions = [
                    "Mitigate: roll back or disable the active change on the slow dependency (lab: chaos reset).",
                    "Do not raise timeouts or add shop replicas: shop is not saturated (runbooks#checkout-latency).",
                    "Confirm: checkout p95 and payments p95 return under budget after mitigation.",
                ]
            else:
                actions = [
                    "Mitigate: roll back the failing dependency or fail fast with a circuit breaker; keep carts.",
                    "Follow the error-budget-burn runbook; track burn rate until it drops below 1x.",
                    "Confirm: 5xx ratio back under 0.5% and alert resolves.",
                ]
            summary = (
                f"{'Checkout latency' if focus == 'latency' else 'Errors'} incident"
                f"{' (' + ', '.join(alerts) + ')' if alerts else ''}. Most likely cause: {cause or 'unclear'}."
            )
            status, confidence = "incident" if alerts else "degraded", "high" if trace and changes else "medium"
        inv = Investigation(
            summary=summary,
            status=status,
            affected_services=affected,
            suspected_cause=cause,
            evidence=ev,
            recommended_actions=actions,
            runbooks=runbooks[:2],
            confidence=confidence,
        )
        return LLMDecision(content=inv.model_dump_json(), prompt_tokens=0, completion_tokens=0)

    @staticmethod
    def _culprit(trace: dict, focus: str) -> dict:
        root = trace["root"]
        if focus == "errors" and trace["error_spans"]:
            others = [s for s in trace["error_spans"] if s["service"] != root["service"]]
            return (others or trace["error_spans"])[-1]
        dominant = [
            s
            for s in trace["slowest_spans"]
            if s["ms"] >= 0.5 * trace["duration_ms"] and s["service"] != root["service"]
        ]
        return min(dominant, key=lambda s: s["ms"]) if dominant else (trace["slowest_spans"] or [root])[0]


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.2f}%"


HEX_ID = re.compile(r"\b[0-9a-f]{16,32}\b")
