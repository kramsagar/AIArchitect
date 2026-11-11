"""Deterministic stand-in for an LLM so the whole agent runs offline, in CI and in benchmarks.

It follows the same contract as a real model: read the messages, either request tool calls or emit the
final AssistantResponse JSON. Fault-injection flags let you exercise the runtime's guard rails."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from ..prompts import REPAIR_PREFIX
from ..schemas import AssistantResponse, ServiceHealth, ToolCall
from ..tokens import count_message_tokens, count_tokens
from ..tools.service_health import assess, burn_rate
from .base import LLMDecision

SERVICE_RE = re.compile(r"\b([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\b")
SERVICE_SUFFIXES = ("-api", "-service", "-gateway", "-db", "-worker", "-svc")
NUM = r"(\d[\d,]*(?:\.\d+)?)"
CAPACITY_WORDS = ("handle", "capacity", "scale", "replicas", "traffic", "headroom")
SRE_WORDS = ("latency", "slo", "incident", "outage", "p99", "error", "health", "service", "pager", "alert")


def _n(s: str) -> float:
    return float(s.replace(",", ""))


def _g(x: float) -> str:
    return f"{x:g}"


def detect_calculation(text: str) -> str | None:
    """Map common SRE questions to a calculator expression (a real model does this from the tool docs)."""
    t = text.lower()
    if m := re.search(r"`([^`]+)`", text):
        return m.group(1)
    if m := re.search(r"(?:calculate|compute|evaluate)\s+([\w\s.+\-*/%^(),]+)", t):
        return m.group(1).strip().rstrip("?.")
    if "error budget" in t and (m := re.search(NUM + r"\s*%", t)):
        days = re.search(NUM + r"\s*(?:days|day|d)\b", t)
        return f"error_budget_minutes({_g(_n(m.group(1)))}, {_g(_n(days.group(1))) if days else 30})"
    if "burn" in t and len(pcts := re.findall(NUM + r"\s*%", t)) >= 2:
        return f"burn_rate({_g(_n(pcts[0]))}, {_g(_n(pcts[1]))})"
    rate = NUM + r"\s*(?:tps|rps|req/s|requests per second)"
    if any(w in t for w in ("concurrency", "in flight", "in-flight", "little")) and (
        m := re.search(rate + r".*?" + NUM + r"\s*ms", t)
    ):
        return f"concurrency({_g(_n(m.group(1)))}, {_g(_n(m.group(2)))})"
    if m := re.search(rate + r".*?" + NUM + r"\s*(?:tps|rps)\s*(?:per|each|/|a)\s*(?:pod|replica|instance)", t):
        headroom = re.search(NUM + r"\s*%\s*headroom", t)
        h = _g(_n(headroom.group(1))) if headroom else "30"
        return f"replicas_needed({_g(_n(m.group(1)))}, {_g(_n(m.group(2)))}, {h})"
    if "availability" in t and (pcts := re.findall(NUM + r"\s*%", t)):
        m = re.search(r"(\d+)\s*(?:\w+\s)?(?:replicas|zones|regions|instances|copies)", t)
        if m and any(w in t for w in ("redundant", "parallel", "independent", "active")):
            return f"parallel_availability({_g(_n(pcts[0]))}, {m.group(1)})"
        if len(pcts) >= 2:
            return "serial_availability(" + ", ".join(_g(_n(p)) for p in pcts) + ")"
    return None


def detect_multiplier(text: str) -> float | None:
    t = text.lower()
    if m := re.search(r"(\d+(?:\.\d+)?)\s*x\b", t):
        return float(m.group(1))
    for word, value in (("double", 2.0), ("triple", 3.0), ("twice", 2.0)):
        if word in t:
            return value
    if m := re.search(r"(\d+)\s*%\s*(?:more|increase|growth)", t):
        return 1 + float(m.group(1)) / 100
    return None


class MockLLM:
    def __init__(self, *, latency_s: float = 0.0, invalid_output_times: int = 0, loop_forever: bool = False) -> None:
        self.latency_s = latency_s
        self.invalid_output_times = invalid_output_times
        self.loop_forever = loop_forever
        self.calls = 0

    # -- contract -------------------------------------------------------------------------------
    def decide(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, timeout_s: float) -> LLMDecision:
        self.calls += 1
        if self.latency_s:
            time.sleep(min(self.latency_s, timeout_s))
        decision = self._decide(messages)
        decision.prompt_tokens = count_message_tokens(messages)
        decision.completion_tokens = count_tokens(
            decision.content or json.dumps([c.model_dump() for c in decision.tool_calls])
        )
        return decision

    # -- "reasoning" ----------------------------------------------------------------------------
    def _decide(self, messages: list[dict[str, Any]]) -> LLMDecision:
        idx, user = next(
            (i, m["content"])
            for i, m in reversed(list(enumerate(messages)))
            if m["role"] == "user" and not str(m["content"]).startswith(REPAIR_PREFIX)
        )
        facts = self._facts(messages)
        done = self._executed(messages[idx + 1 :])

        if self.loop_forever:
            return self._calls([("get_service_health", {"service": "checkout-api", "window_minutes": 15})], done)

        text = user.lower()
        services = list(dict.fromkeys(s for s in SERVICE_RE.findall(text) if s.endswith(SERVICE_SUFFIXES)))
        multiplier = detect_multiplier(text)
        capacity_ask = multiplier is not None or any(w in text for w in CAPACITY_WORDS)
        follow_up_ref = re.search(r"\b(it|this service|that service)\b", text)
        if not services and capacity_ask and follow_up_ref and facts.get("last_service"):
            services = [facts["last_service"]]
        calc = None if services else detect_calculation(user)

        health = {a["service"]: out for name, a, out in done if name == "get_service_health"}
        pending = [("get_service_health", {"service": s, "window_minutes": 15}) for s in services if s not in health]
        if pending:
            return self._calls(pending, done)

        calcs = {a["expression"]: out for name, a, out in done if name == "capacity_calculator"}
        if capacity_ask and services:
            for s in services:
                out = health.get(s)
                if out and out.get("ok"):
                    h = out["output"]
                    per = round(h["rps"] / h["replicas"], 1)
                    expr = f"replicas_needed({_g(h['rps'] * (multiplier or 1.0))}, {_g(per)}, 30)"
                    if expr not in calcs:
                        pending.append(("capacity_calculator", {"expression": expr}))
        if calc and calc not in calcs:
            pending.append(("capacity_calculator", {"expression": calc}))
        if pending:
            return self._calls(pending, done)

        if self.invalid_output_times > 0:
            self.invalid_output_times -= 1
            return LLMDecision(content='{"answer": "checkout-api looks bad", "severity": "very bad"}')
        return LLMDecision(content=self._final(text, services, health, calcs, multiplier).model_dump_json())

    @staticmethod
    def _facts(messages: list[dict[str, Any]]) -> dict[str, str]:
        for m in messages:
            content = str(m.get("content") or "")
            if m["role"] in ("system", "developer") and content.startswith("Session facts"):
                return dict(kv.split("=", 1) for kv in content.split(": ", 1)[1].split(", ") if "=" in kv)
        return {}

    @staticmethod
    def _executed(messages: list[dict[str, Any]]) -> list[tuple[str, dict, dict]]:
        calls: dict[str, tuple[str, dict]] = {}
        out: list[tuple[str, dict, dict]] = []
        for m in messages:
            for c in m.get("tool_calls") or []:
                try:
                    args = json.loads(c["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                calls[c["id"]] = (c["function"]["name"], args)
            if m["role"] == "tool" and m["tool_call_id"] in calls:
                name, args = calls[m["tool_call_id"]]
                out.append((name, args, json.loads(m["content"])))
        return out

    def _calls(self, pending: list[tuple[str, dict]], done: list) -> LLMDecision:
        base = len(done)
        return LLMDecision(
            tool_calls=[
                ToolCall(id=f"call_{base + i + 1}", name=name, arguments=json.dumps(args))
                for i, (name, args) in enumerate(pending)
            ]
        )

    # -- final answer composition -----------------------------------------------------------------
    def _final(
        self,
        text: str,
        services: list[str],
        health: dict[str, dict],
        calcs: dict[str, dict],
        multiplier: float | None,
    ) -> AssistantResponse:
        if not services and not calcs:
            if any(w in text for w in SRE_WORDS):
                return AssistantResponse(
                    answer="I can check live golden signals for a service or run SLO/capacity math.",
                    intent="general",
                    severity="unknown",
                    recommendations=[],
                    tools_used=[],
                    confidence="low",
                    follow_up="Which service should I look at (e.g. checkout-api)?",
                )
            return AssistantResponse(
                answer="I am an SRE copilot: I can only help with service health, SLOs and capacity.",
                intent="unsupported",
                severity="unknown",
                recommendations=[],
                tools_used=[],
                confidence="high",
                follow_up=None,
            )

        parts: list[str] = []
        recs: list[str] = []
        severities: list[str] = []
        failed = False
        for s in services:
            out = health[s]
            if not out.get("ok"):
                failed = True
                severities.append("unknown")
                parts.append(f"{s}: no data ({out.get('error_type')}: {out.get('error')}).")
                continue
            h = ServiceHealth.model_validate(out["output"])
            sev, issues = assess(h)
            severities.append(sev)
            parts.append(
                f"{h.service} is {sev.upper()}: p99 {h.latency_p99_ms:.0f}ms (SLO {h.slo.latency_p99_ms:.0f}ms), "
                f"errors {h.error_rate_pct}% (burn {burn_rate(h):.1f}x), {h.rps:,.0f} rps on {h.replicas} pods, "
                f"saturation {h.saturation_pct:.0f}%."
            )
            if h.recent_change and sev != "ok":
                recs.append(f"Correlate with recent change '{h.recent_change}'; roll back if the regression matches.")
            if burn_rate(h) >= 10:
                recs.append(f"Page the {h.service} owners: fast error-budget burn ({burn_rate(h):.0f}x).")
            for dep, state in h.dependencies.items():
                if state != "healthy":
                    recs.append(
                        f"Check dependency {dep} ({state}); enable fallback or shed load if it keeps degrading."
                    )
            if h.saturation_pct >= 85:
                recs.append(f"Scale {h.service} out or raise HPA max; saturation is {h.saturation_pct:.0f}%.")
            if not issues:
                recs.append("No action needed; keep watching the burn-rate alerts.")

        for expr, out in calcs.items():
            if not out.get("ok"):
                failed = True
                parts.append(f"Could not compute {expr}: {out.get('error')}.")
                continue
            parts.append(self._describe_calc(expr, out["output"]["result"], services, health, multiplier))

        order = ["critical", "warning", "unknown", "ok"]
        severity = next((s for s in order if s in severities), "unknown")
        used = sorted(
            {"get_service_health" for s in services if health[s].get("ok")}
            | ({"capacity_calculator"} if any(o.get("ok") for o in calcs.values()) else set())
        )
        intent = "health_and_capacity" if services and calcs else "service_health" if services else "capacity_planning"
        return AssistantResponse(
            answer=" ".join(parts),
            intent=intent,
            severity=severity,
            recommendations=recs[:5],
            tools_used=used,
            confidence="low" if failed else "high",
            follow_up=None,
        )

    @staticmethod
    def _describe_calc(expr: str, result: float, services: list[str], health: dict, mult: float | None) -> str:
        fn = expr.split("(", 1)[0].strip()
        if fn == "replicas_needed" and services:
            h = health[services[0]].get("output") or {}
            return (
                f"For {mult or 1:g}x traffic it needs {result:.0f} replicas (30% headroom) vs "
                f"{h.get('replicas', '?')} today."
            )
        labels = {
            "error_budget_minutes": "Error budget: {r:,.1f} minutes in the window.",
            "burn_rate": "Burn rate: {r:.1f}x (1x = budget lasts exactly the SLO window).",
            "concurrency": "Little's law: ~{r:,.0f} requests in flight; size pools/threads above that.",
            "replicas_needed": "Replicas needed: {r:.0f}.",
            "serial_availability": "Composite availability (serial): {r:.4f}%.",
            "parallel_availability": "Availability with redundancy: {r:.6f}%.",
        }
        return labels.get(fn, f"{expr} = {{r:,.4f}}.").format(r=result)
