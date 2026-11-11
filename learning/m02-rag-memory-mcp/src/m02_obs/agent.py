"""Investigator agent = MCP client + the M1 loop. Tools are discovered from the MCP server at runtime (no tool code in
the agent), parallel tool calls run concurrently, and the final answer is checked against what the tools returned."""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import timedelta
from typing import Any

from m01_agent.config import AgentConfig
from m01_agent.errors import LLMError
from m01_agent.resilience import Deadline
from m01_agent.schemas import ToolCall
from m01_agent.tools.registry import format_validation_error
from mcp import ClientSession
from pydantic import BaseModel, Field, ValidationError

from .memory import LongTermMemory, SessionMemory
from .prompts import DEVELOPER_PROMPT, SYSTEM_PROMPT, memory_message, repair_message
from .schemas import Investigation

TOOL_SOURCE = {
    "get_slo_status": "prometheus",
    "list_firing_alerts": "prometheus",
    "promql_query": "prometheus",
    "search_traces": "jaeger",
    "get_trace": "jaeger",
    "search_logs": "splunk",
    "search_runbooks": "runbook",
    "get_recent_changes": "changes",
}
IDENTIFIER = re.compile(r"\b[0-9a-f]{16,32}\b|\b[\w-]+#[\w-]+\b|\bShopSphere\w+\b|\bepisode:\d+\b")
MAX_RESULT_CHARS = 6000


class ToolRun(BaseModel):
    name: str
    arguments: dict[str, Any]
    ok: bool
    ms: float
    error: str | None = None


class Step(BaseModel):
    step: int
    kind: str
    tools: list[ToolRun] = Field(default_factory=list)
    note: str | None = None


class InvestigationResult(BaseModel):
    run_id: str
    status: str
    investigation: Investigation
    steps: list[Step]
    tool_calls: int
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    elapsed_ms: float
    dropped_evidence: list[str] = Field(default_factory=list)
    recalled_episodes: list[int] = Field(default_factory=list)


def mcp_tools_to_schemas(tools) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description or "", "parameters": t.inputSchema},
        }
        for t in tools
    ]


def ground(inv: Investigation, observed: dict[str, str]) -> tuple[Investigation, list[str]]:
    """Drop evidence the tools cannot back up. Identifiers in a ref (trace ids, chunk ids, alert names, episode ids)
    must appear verbatim in a tool result; refs without identifiers need their source tool to have run successfully."""
    everything = "\n".join(observed.values())
    kept, dropped = [], []
    for e in inv.evidence:
        ids = IDENTIFIER.findall(e.ref)
        ok = all(i in everything for i in ids) if ids else e.source in observed
        (kept if ok else dropped).append(e)
    runbooks = [r for r in inv.runbooks if r in observed.get("runbook", "")]
    confidence = inv.confidence
    if dropped or not kept:
        confidence = "low" if not kept or confidence == "medium" else "medium"
    fixed = inv.model_copy(update={"evidence": kept, "runbooks": runbooks, "confidence": confidence})
    return fixed, [f"{e.source}:{e.ref}" for e in dropped]


class Investigator:
    def __init__(
        self,
        llm,
        session: ClientSession,
        config: AgentConfig | None = None,
        session_memory: SessionMemory | None = None,
        long_term: LongTermMemory | None = None,
    ) -> None:
        self.llm = llm
        self.session = session
        self.config = config or AgentConfig(max_steps=8, max_tool_calls=14, run_timeout_s=180, llm_timeout_s=60)
        self.session_memory = session_memory
        self.long_term = long_term
        self._schemas: list[dict[str, Any]] | None = None

    async def tool_schemas(self) -> list[dict[str, Any]]:
        if self._schemas is None:
            self._schemas = mcp_tools_to_schemas((await self.session.list_tools()).tools)
        return self._schemas

    async def _call(self, call: ToolCall, deadline: Deadline) -> tuple[ToolRun, str]:
        start = time.perf_counter()
        try:
            args = json.loads(call.arguments or "{}")
        except json.JSONDecodeError as exc:
            return ToolRun(name=call.name, arguments={}, ok=False, ms=0, error="invalid JSON"), json.dumps(
                {"ok": False, "error": f"arguments are not valid JSON: {exc.msg}"}
            )
        try:
            res = await self.session.call_tool(
                call.name, args, read_timeout_seconds=timedelta(seconds=deadline.cap(self.config.tool_timeout_s * 10))
            )
            text = "\n".join(getattr(c, "text", "") for c in res.content)
            ok, error = not res.isError, (text[:300] if res.isError else None)
        except Exception as exc:  # transport failure or timeout: the model gets told, the loop continues
            text, ok, error = "", False, f"{type(exc).__name__}: {exc}"[:300]
        run = ToolRun(
            name=call.name, arguments=args, ok=ok, ms=round((time.perf_counter() - start) * 1000, 1), error=error
        )
        if not ok:
            return run, json.dumps({"ok": False, "error": error})
        try:
            output: Any = json.loads(text)
        except json.JSONDecodeError:
            output = text
        content = json.dumps({"ok": True, "output": output})
        if len(content) > MAX_RESULT_CHARS:  # token budget: never let one tool result flood the context
            content = json.dumps({"ok": True, "truncated": True, "output_prefix": text[:MAX_RESULT_CHARS]})
        return run, content

    def _context(self, question: str, episodes: list[dict]) -> list[dict[str, Any]]:
        dev = self.config.developer_role
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": dev, "content": DEVELOPER_PROMPT},
        ]
        if self.long_term is not None and (facts := self.long_term.facts()):
            msgs.append({"role": dev, "content": "Known facts:\n" + "\n".join(f"- {k}: {v}" for k, v in facts.items())})
        if episodes:
            msgs.append({"role": dev, "content": memory_message(episodes)})
        if self.session_memory is not None:
            msgs += self.session_memory.messages()
        msgs.append({"role": "user", "content": question})
        return msgs

    async def run(self, question: str) -> InvestigationResult:
        cfg = self.config
        run_id, started = uuid.uuid4().hex[:12], time.perf_counter()
        deadline = Deadline(cfg.run_timeout_s)
        episodes = self.long_term.recall(question) if self.long_term is not None else []
        messages = self._context(question, episodes)
        observed: dict[str, str] = {}
        if episodes:
            observed["memory"] = "\n".join(f"episode:{e['id']} {e['root_cause']}" for e in episodes)
        steps: list[Step] = []
        tools = await self.tool_schemas()
        tool_calls = llm_calls = ptok = ctok = repairs = 0
        status, inv, dropped = "max_steps", None, []

        for step in range(1, cfg.max_steps + 1):
            if deadline.expired():
                status = "timeout"
                break
            try:
                decision = await asyncio.to_thread(
                    self.llm.decide, messages, tools, timeout_s=deadline.cap(cfg.llm_timeout_s)
                )
            except LLMError as exc:
                steps.append(Step(step=step, kind="llm_error", note=str(exc)[:300]))
                status = "llm_error"
                break
            llm_calls += 1
            ptok, ctok = ptok + decision.prompt_tokens, ctok + decision.completion_tokens
            if decision.tool_calls:
                if tool_calls + len(decision.tool_calls) > cfg.max_tool_calls:
                    steps.append(Step(step=step, kind="tool_budget", note="tool-call budget exhausted"))
                    status = "tool_budget"
                    break
                messages.append(
                    {
                        "role": "assistant",
                        "content": decision.content,
                        "tool_calls": [
                            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                            for c in decision.tool_calls
                        ],
                    }
                )
                results = await asyncio.gather(*(self._call(c, deadline) for c in decision.tool_calls))
                for call, (run, content) in zip(decision.tool_calls, results, strict=False):
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
                    if run.ok:
                        src = TOOL_SOURCE.get(call.name, call.name)
                        observed[src] = observed.get(src, "") + "\n" + content
                tool_calls += len(results)
                steps.append(Step(step=step, kind="tool_calls", tools=[r for r, _ in results]))
                continue
            try:
                inv = Investigation.model_validate_json(decision.content or "")
            except ValidationError as exc:
                errors = format_validation_error(exc)
                steps.append(Step(step=step, kind="invalid_output", note=errors[:300]))
                if repairs >= cfg.max_repairs:
                    status = "invalid_output"
                    break
                repairs += 1
                messages += [
                    {"role": "assistant", "content": decision.content or ""},
                    {"role": "user", "content": repair_message(errors)},
                ]
                continue
            inv, dropped = ground(inv, observed)
            steps.append(
                Step(step=step, kind="final", note=f"dropped {len(dropped)} ungrounded evidence" if dropped else None)
            )
            status = "completed"
            break

        if inv is None or status != "completed":
            inv = Investigation(
                summary=f"Investigation incomplete ({status}). Collected data from {tool_calls} tool call(s); check "
                "the Grafana SLO dashboard and the firing alerts directly.",
                status="unknown",
                affected_services=[],
                suspected_cause=None,
                evidence=[],
                recommended_actions=["Open Grafana 'ShopSphere – SLO & Golden Signals' and Prometheus /alerts."],
                runbooks=[],
                confidence="low",
            )
        else:
            if self.session_memory is not None:
                self.session_memory.add(question, inv.summary)
            if self.long_term is not None and inv.status in ("incident", "degraded") and inv.suspected_cause:
                self.long_term.record_episode(question, inv.summary, inv.suspected_cause, inv.affected_services)
        return InvestigationResult(
            run_id=run_id,
            status=status,
            investigation=inv,
            steps=steps,
            tool_calls=tool_calls,
            llm_calls=llm_calls,
            prompt_tokens=ptok,
            completion_tokens=ctok,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            dropped_evidence=dropped,
            recalled_episodes=[e["id"] for e in episodes],
        )
