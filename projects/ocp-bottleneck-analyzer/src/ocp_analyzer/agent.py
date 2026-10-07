"""Tool-calling LLM agent that investigates the snapshot like an SRE and writes the RCA."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import AgentStep, ContainerStats, Finding, LogInsight, Snapshot
from .utils import fmt_bytes, fmt_cpu, fmt_pct, to_json

TOOL_OUTPUT_LIMIT = 6000

SYSTEM_PROMPT = """You are a senior OpenShift SRE performing a performance bottleneck investigation.
You have read-only tools over a snapshot of one deployment (spec, pods, events, HPA, nodes, quotas,
container logs, Prometheus metrics) plus live PromQL access when available.

Method:
1. Start from the rule-engine findings, then verify and extend them with the tools.
2. Correlate signals across layers (metrics <-> logs <-> events <-> spec). Prefer evidence over guesses.
3. Distinguish symptoms (latency, restarts) from causes (limits, capacity, dependencies).
4. Use at most a handful of tool calls; stop when you have enough evidence.

Final answer (Markdown, concise, no preamble):
### Executive summary
2-3 sentences: is the deployment healthy, what is the primary bottleneck.
### Bottlenecks (ranked)
Numbered list; each with severity, evidence (numbers!) and affected resources.
### Root cause analysis
Causal chain from root cause to user impact.
### Recommendations
Concrete actions, ordered by impact, including example `oc` commands or YAML snippets.
"""


@dataclass
class LLMConfig:
    api_key: str | None = None
    base_url: str | None = None
    model: str = "gpt-4o-mini"
    provider: str = "openai"
    api_version: str = "2024-06-01"
    temperature: float = 0.1
    max_steps: int = 8

    @classmethod
    def from_env(cls) -> LLMConfig:
        provider = os.getenv("LLM_PROVIDER", "azure" if os.getenv("AZURE_OPENAI_ENDPOINT") else "openai")
        return cls(
            api_key=os.getenv("AZURE_OPENAI_API_KEY") if provider == "azure" else os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("AZURE_OPENAI_ENDPOINT") if provider == "azure" else os.getenv("OPENAI_BASE_URL"),
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            provider=provider,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01"),
        )

    @property
    def enabled(self) -> bool:
        # Local OpenAI-compatible servers (Ollama, vLLM) often need no key.
        return bool(self.api_key or self.base_url)

    def client(self) -> Any:
        import openai

        if self.provider == "azure":
            return openai.AzureOpenAI(api_key=self.api_key, azure_endpoint=self.base_url, api_version=self.api_version)
        return openai.OpenAI(api_key=self.api_key or "not-needed", base_url=self.base_url or None)


def _tool(name: str, description: str, properties: dict | None = None, required: list | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
        },
    }


TOOLS = [
    _tool("get_rule_findings", "Findings already produced by the deterministic rule engine."),
    _tool("get_deployment_overview", "Replicas, rollout conditions, strategy, container specs, probes, HPA."),
    _tool("get_container_stats", "Per pod/container status, restarts, requests/limits and live usage."),
    _tool(
        "get_events",
        "Kubernetes events for the deployment, its ReplicaSets, pods and HPA (newest first).",
        {"warnings_only": {"type": "boolean"}, "limit": {"type": "integer"}},
    ),
    _tool("get_node_status", "Conditions, allocatable resources and utilisation of nodes hosting the pods."),
    _tool("get_log_insights", "Per container log categories (timeouts, OOM, db pool, ...) and top templates."),
    _tool(
        "get_logs",
        "Raw log lines for one container, optionally filtered by a regex.",
        {
            "pod": {"type": "string"},
            "container": {"type": "string"},
            "previous": {"type": "boolean", "description": "logs of the previous (crashed) instance"},
            "grep": {"type": "string", "description": "case-insensitive regex filter"},
            "tail": {"type": "integer"},
        },
        ["pod", "container"],
    ),
    _tool("get_metrics_summary", "Collected Prometheus instant metrics (cpu, memory, throttling, network, p95)."),
    _tool(
        "run_promql",
        "Run a read-only PromQL instant query against the cluster's Prometheus/Thanos.",
        {"query": {"type": "string"}},
        ["query"],
    ),
]


class BottleneckAgent:
    def __init__(
        self,
        config: LLMConfig,
        snapshot: Snapshot,
        containers: list[ContainerStats],
        findings: list[Finding],
        log_insights: list[LogInsight],
        prom: Any | None = None,
        client: Any | None = None,
        on_step: Callable[[AgentStep], None] | None = None,
    ):
        self.config = config
        self.snapshot = snapshot
        self.containers = containers
        self.findings = findings
        self.log_insights = log_insights
        self.prom = prom
        self.client = client or config.client()
        self.on_step = on_step
        self.trace: list[AgentStep] = []
        self._handlers: dict[str, Callable[..., Any]] = {
            "get_rule_findings": self.get_rule_findings,
            "get_deployment_overview": self.get_deployment_overview,
            "get_container_stats": self.get_container_stats,
            "get_events": self.get_events,
            "get_node_status": self.get_node_status,
            "get_log_insights": self.get_log_insights,
            "get_logs": self.get_logs,
            "get_metrics_summary": self.get_metrics_summary,
            "run_promql": self.run_promql,
        }

    # tools ---------------------------------------------------------------------------------
    def get_rule_findings(self) -> Any:
        return [f.model_dump(mode="json") for f in self.findings]

    def get_deployment_overview(self) -> Any:
        dep = self.snapshot.deployment
        spec = dep.get("spec", {})
        tmpl = spec.get("template", {}).get("spec", {})
        hpa = self.snapshot.hpa
        return {
            "name": self.snapshot.deployment_name,
            "namespace": self.snapshot.namespace,
            "replicas": spec.get("replicas"),
            "status": {k: v for k, v in dep.get("status", {}).items() if k != "conditions"},
            "conditions": [
                {k: c.get(k) for k in ("type", "status", "reason", "message")}
                for c in dep.get("status", {}).get("conditions", [])
            ],
            "strategy": spec.get("strategy"),
            "containers": [
                {
                    "name": c["name"],
                    "image": c.get("image"),
                    "resources": c.get("resources"),
                    "readinessProbe": c.get("readinessProbe"),
                    "livenessProbe": c.get("livenessProbe"),
                    "env_names": [e["name"] for e in c.get("env", [])],
                }
                for c in tmpl.get("containers", [])
            ],
            "hpa": {"spec": hpa.get("spec"), "status": hpa.get("status")} if hpa else None,
        }

    def get_container_stats(self) -> Any:
        return [
            {
                **c.model_dump(exclude_none=True),
                "cpu": f"{fmt_cpu(c.cpu_usage)} used / {fmt_cpu(c.cpu_request)} req / {fmt_cpu(c.cpu_limit)} lim",
                "memory": f"{fmt_bytes(c.mem_usage)} used / {fmt_bytes(c.mem_limit)} lim ({fmt_pct(c.mem_limit_util)})",
            }
            for c in self.containers
        ]

    def get_events(self, warnings_only: bool = True, limit: int = 30) -> Any:
        return [
            {
                "type": e.get("type"),
                "reason": e.get("reason"),
                "object": f"{(e.get('involvedObject') or {}).get('kind')}/"
                f"{(e.get('involvedObject') or {}).get('name')}",
                "count": e.get("count"),
                "last": e.get("lastTimestamp") or e.get("eventTime"),
                "message": e.get("message"),
            }
            for e in self.snapshot.events
            if not warnings_only or e.get("type") == "Warning"
        ][:limit]

    def get_node_status(self) -> Any:
        util = {
            k: {s["labels"].get("instance"): round(s["value"], 3) for s in self.snapshot.instant.get(k, [])}
            for k in ("node_cpu_util", "node_memory_util")
        }
        return {
            name: {
                "conditions": {c["type"]: c["status"] for c in node.get("status", {}).get("conditions", [])},
                "allocatable": node.get("status", {}).get("allocatable"),
                "cpu_util": util["node_cpu_util"].get(name),
                "memory_util": util["node_memory_util"].get(name),
            }
            for name, node in self.snapshot.nodes.items()
        }

    def get_log_insights(self) -> Any:
        return [li.model_dump() for li in self.log_insights if li.category_counts]

    def get_logs(
        self, pod: str, container: str, previous: bool = False, grep: str | None = None, tail: int = 80
    ) -> Any:
        key = f"{pod}/{container}" + ("#previous" if previous else "")
        text = self.snapshot.logs.get(key)
        if text is None:
            return {"error": f"no logs collected for {key}", "available": sorted(self.snapshot.logs)}
        lines = text.splitlines()
        if grep:
            try:
                rx = re.compile(grep, re.I)
            except re.error as exc:
                return {"error": f"invalid regex: {exc}"}
            lines = [ln for ln in lines if rx.search(ln)]
        return lines[-max(1, min(tail, 200)) :]

    def get_metrics_summary(self) -> Any:
        return {
            key: [{**s["labels"], "value": round(s["value"], 4)} for s in samples]
            for key, samples in self.snapshot.instant.items()
        }

    def run_promql(self, query: str) -> Any:
        if not self.prom:
            return {"error": "Prometheus is not available in this session"}
        try:
            return self.prom.query(query)[:50]
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    # loop ----------------------------------------------------------------------------------
    def _call_tool(self, name: str, raw_args: str) -> str:
        handler = self._handlers.get(name)
        args: dict[str, Any] = {}
        try:
            args = json.loads(raw_args or "{}")
            result = handler(**args) if handler else {"error": f"unknown tool {name}"}
        except Exception as exc:  # noqa: BLE001 - surface tool errors to the model
            result = {"error": f"{type(exc).__name__}: {exc}"}
        text = to_json(result, TOOL_OUTPUT_LIMIT)
        step = AgentStep(step=len(self.trace) + 1, tool=name, arguments=args, result_preview=text[:800])
        self.trace.append(step)
        if self.on_step:
            self.on_step(step)
        return text

    def _initial_prompt(self) -> str:
        top = [f"- [{f.severity.value}] {f.title} ({f.resource})" for f in self.findings[:15]]
        return (
            f"Investigate deployment `{self.snapshot.namespace}/{self.snapshot.deployment_name}` "
            f"for performance bottlenecks. Metrics source: {self.snapshot.metrics_source}. "
            f"Pods: {len(self.snapshot.pods)}. Rule-engine findings:\n"
            + ("\n".join(top) or "- none")
            + "\nUse the tools to verify, correlate and find anything the rules missed, then write the report."
        )

    def run(self) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._initial_prompt()},
        ]
        for step in range(self.config.max_steps):
            final_turn = step == self.config.max_steps - 1
            resp = self.client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                tools=TOOLS,
                tool_choice="none" if final_turn else "auto",
                temperature=self.config.temperature,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return (msg.content or "").strip()
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            for tc in msg.tool_calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": self._call_tool(tc.function.name, tc.function.arguments),
                    }
                )
        return "Agent stopped without producing a final answer."
