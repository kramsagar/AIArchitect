"""The agent loop: Observe -> Decide -> Act -> Observe, with explicit state, budgets and graceful failure.

observe: build context (policy + contract + memory + user input + tool results so far)
decide:  ask the LLM -> tool calls OR a final answer
act:     execute tool calls through the registry (validation, timeout, retry, breaker, cache)
observe: append observations; loop until a schema-valid final answer or a guard trips
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from pydantic import ValidationError

from .config import AgentConfig
from .errors import LLMError
from .llm.base import LLMClient
from .memory import ConversationMemory
from .prompts import DEVELOPER_PROMPT, SYSTEM_PROMPT, facts_message, repair_message
from .resilience import Deadline
from .schemas import AgentResult, AssistantResponse, Observation, RunStatus, StepTrace, Usage
from .telemetry import METRICS, log_event, span
from .tools.registry import ToolRegistry, format_validation_error

FALLBACK_REASONS = {
    "max_steps": "the step limit was reached",
    "tool_budget": "the tool-call budget was exhausted",
    "timeout": "the time budget ran out",
    "invalid_output": "the model kept returning invalid output",
    "llm_error": "the model provider is unavailable",
}


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        config: AgentConfig | None = None,
        memory: ConversationMemory | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.config = config or AgentConfig()
        self.memory = memory

    # -- observe: context assembly ------------------------------------------------------------------
    def build_context(self, user_input: str) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": self.config.developer_role, "content": DEVELOPER_PROMPT},
        ]
        if self.memory is not None:
            if self.memory.facts:
                messages.append({"role": self.config.developer_role, "content": facts_message(self.memory.facts)})
            messages += self.memory.messages()
        messages.append({"role": "user", "content": user_input})
        return messages

    # -- the loop -----------------------------------------------------------------------------------
    def run(self, user_input: str) -> AgentResult:
        cfg = self.config
        run_id = uuid.uuid4().hex[:12]
        deadline = Deadline(cfg.run_timeout_s)
        usage = Usage()
        steps: list[StepTrace] = []
        executed: dict[tuple[str, str], Observation] = {}
        messages = self.build_context(user_input)
        response: AssistantResponse | None = None
        status: RunStatus = "max_steps"
        repairs = 0
        started = time.perf_counter()

        with span("agent.run", run_id) as run_rec:
            for step in range(1, cfg.max_steps + 1):
                if deadline.expired():
                    status = "timeout"
                    break
                # DECIDE
                try:
                    with span("llm", run_id, step=step):
                        decision = self.llm.decide(
                            messages, self.registry.schemas(), timeout_s=deadline.cap(cfg.llm_timeout_s)
                        )
                except LLMError as exc:
                    steps.append(StepTrace(step=step, decision="final", note=f"llm_error: {exc}"))
                    status = "llm_error"
                    break
                usage.llm_calls += 1
                usage.prompt_tokens += decision.prompt_tokens
                usage.completion_tokens += decision.completion_tokens

                # ACT + OBSERVE
                if decision.tool_calls:
                    if usage.tool_calls + len(decision.tool_calls) > cfg.max_tool_calls:
                        steps.append(
                            StepTrace(
                                step=step,
                                decision="tool_calls",
                                tool_calls=decision.tool_calls,
                                note="tool-call budget exceeded; calls not executed",
                            )
                        )
                        status = "tool_budget"
                        break
                    messages.append(self._assistant_tool_message(decision.content, decision.tool_calls))
                    observations = []
                    for call in decision.tool_calls:
                        obs = self._act(call, executed, run_id, deadline, usage)
                        messages.append({"role": "tool", "tool_call_id": call.id, "content": obs.to_model_content()})
                        observations.append(obs)
                    steps.append(
                        StepTrace(
                            step=step, decision="tool_calls", tool_calls=decision.tool_calls, observations=observations
                        )
                    )
                    continue

                # FINAL ANSWER: validate against the contract, repair if needed
                try:
                    response = AssistantResponse.model_validate_json(decision.content or "")
                except ValidationError as exc:
                    errors = format_validation_error(exc)
                    steps.append(StepTrace(step=step, decision="invalid_output", note=errors[:300]))
                    if repairs >= cfg.max_repairs:
                        status = "invalid_output"
                        break
                    repairs += 1
                    messages.append({"role": "assistant", "content": decision.content or ""})
                    messages.append({"role": "user", "content": repair_message(errors)})
                    continue
                response = self._ground(response, executed)
                steps.append(StepTrace(step=step, decision="final"))
                status = "completed"
                break

            if status != "completed" or response is None:
                response = self._fallback(status, executed)
            elif self.memory is not None:
                self.memory.add(user_input, response, self._facts(executed))

            usage.elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            run_rec.update(status=status, steps=len(steps), llm_calls=usage.llm_calls, tool_calls=usage.tool_calls)
        METRICS.inc(f"agent.status.{status}")
        return AgentResult(run_id=run_id, status=status, response=response, steps=steps, usage=usage)

    # -- helpers ------------------------------------------------------------------------------------
    def _act(self, call, executed, run_id: str, deadline: Deadline, usage: Usage) -> Observation:
        try:
            normalized = json.dumps(json.loads(call.arguments), sort_keys=True)
        except json.JSONDecodeError:
            normalized = call.arguments
        key = (call.name, normalized)
        if key in executed:
            # Loop guard: identical call already ran this turn - do not pay for it again.
            log_event("duplicate_tool_call", run_id=run_id, tool=call.name)
            return Observation(
                tool_call_id=call.id,
                tool_name=call.name,
                ok=False,
                error="duplicate call: this exact call already ran in this turn; use the earlier result",
                error_type="duplicate_call",
                attempts=0,
            )
        obs = self.registry.execute(call, run_id=run_id, deadline=deadline)
        executed[key] = obs
        usage.tool_calls += 1
        return obs

    @staticmethod
    def _assistant_tool_message(content: str | None, calls) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in calls
            ],
        }

    @staticmethod
    def _ground(response: AssistantResponse, executed: dict[tuple[str, str], Observation]) -> AssistantResponse:
        """Never trust the model's self-report for audit fields: tools_used comes from what actually ran."""
        used = sorted({o.tool_name for o in executed.values() if o.ok})
        any_failed = any(not o.ok for o in executed.values())
        confidence = "low" if any_failed and response.confidence == "high" else response.confidence
        return response.model_copy(update={"tools_used": used, "confidence": confidence})

    @staticmethod
    def _facts(executed: dict[tuple[str, str], Observation]) -> dict[str, str]:
        facts: dict[str, str] = {}
        for obs in executed.values():
            if obs.ok and obs.tool_name == "get_service_health" and obs.output:
                facts["last_service"] = obs.output["service"]
        return facts

    @staticmethod
    def _fallback(status: str, executed: dict[tuple[str, str], Observation]) -> AssistantResponse:
        ok = [o for o in executed.values() if o.ok]
        partial = f" Partial data was collected from {len(ok)} tool call(s)." if ok else ""
        return AssistantResponse(
            answer=f"I could not complete the analysis because {FALLBACK_REASONS.get(status, status)}.{partial}",
            intent="general",
            severity="unknown",
            recommendations=["Check the service dashboards directly and retry the question shortly."],
            tools_used=sorted({o.tool_name for o in ok}),
            confidence="low",
            follow_up=None,
        )
