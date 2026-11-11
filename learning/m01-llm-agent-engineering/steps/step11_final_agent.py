"""Step 11 - the complete Module 1 agent. Adds the last production layers on top of steps 5-10:
a validated final contract (AssistantResponse) + one repair attempt, grounding (audit fields come from what
really ran), budgets (steps, tool calls, wall-clock deadline) and a safe fallback answer.

Run:  python steps/step11_final_agent.py
      python steps/step11_final_agent.py "Can checkout-api handle 2x traffic?"
      python steps/step11_final_agent.py --chat
"""

import json
import sys
import time
from functools import partial
from typing import Literal

from common import MODEL, client, text_of
from pydantic import BaseModel, Field, ValidationError
from step03_tool_schema import HEALTH_TOOL
from step06_two_tools import CALC_TOOL, SYSTEM6
from step07_tool_errors import safe_execute
from step09_breaker_cache import Protected
from step10_memory import Memory


class AssistantResponse(BaseModel):
    answer: str = Field(description="Concise answer for an on-call engineer, with the key numbers")
    severity: Literal["ok", "warning", "critical", "unknown"]
    recommendations: list[str] = Field(description="Ordered next actions")
    tools_used: list[str]
    confidence: Literal["high", "medium", "low"]


SYSTEM11 = SYSTEM6 + (
    "\nSeverity: critical = p99 above SLO or burn rate >= 10; warning = burn rate > 1 or saturation >= 85%; else ok."
    "\nGather facts with tools FIRST. When done, reply with ONLY a JSON object (no prose, no code fences) with keys: "
    "answer, severity (ok|warning|critical|unknown), recommendations (list), tools_used (list), "
    "confidence (high|medium|low)."
)


def fallback(reason: str, used: set) -> AssistantResponse:
    return AssistantResponse(
        answer=f"I could not complete the analysis: {reason}.",
        severity="unknown",
        recommendations=["Check the service dashboards directly and retry shortly."],
        tools_used=sorted(used),
        confidence="low",
    )


def run_final_agent(c, question, tools, execute, history=None, max_steps=6, max_tool_calls=8, deadline_s=60.0):
    started = time.monotonic()
    messages = list(history or []) + [{"role": "user", "content": question}]
    used, any_failed, tool_calls, repaired = set(), False, 0, False
    for step in range(1, max_steps + 1):
        if time.monotonic() - started > deadline_s:
            return fallback("the time budget ran out", used)
        resp = c.messages.create(
            model=MODEL, max_tokens=1200, system=SYSTEM11, tools=[t.spec() for t in tools.values()], messages=messages
        )
        calls = [b for b in resp.content if b.type == "tool_use"]
        if calls:
            tool_calls += len(calls)
            if tool_calls > max_tool_calls:
                return fallback("the tool-call budget was exhausted", used)
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for call in calls:
                result = execute(call, tools)
                any_failed |= bool(result.get("is_error"))
                if not result.get("is_error"):
                    used.add(call.name)
                print(f"[step {step}] act {call.name}({json.dumps(call.input)}) -> {result['content'][:80]}")
                results.append(result)
            messages.append({"role": "user", "content": results})
            continue
        text = text_of(resp).strip()
        try:
            answer = AssistantResponse.model_validate_json(text.removeprefix("```json").removesuffix("```"))
        except ValidationError as exc:  # REPAIR once: show the model its exact mistakes
            print(f"[step {step}] invalid final JSON -> asking for a repair")
            if repaired:
                return fallback("the model kept returning invalid output", used)
            repaired = True
            messages += [
                {"role": "assistant", "content": text or "(empty)"},
                {"role": "user", "content": f"Your reply did not match the schema: {exc}. Reply with ONLY the JSON."},
            ]
            continue
        print(f"[step {step}] final answer (validated)")
        # GROUND: never trust the model's self-report for audit fields.
        confidence = "low" if any_failed and answer.confidence == "high" else answer.confidence
        return answer.model_copy(update={"tools_used": sorted(used), "confidence": confidence})
    return fallback("the step limit was reached", used)


def main() -> None:
    c = client()
    tools = {t.name: t for t in (HEALTH_TOOL, CALC_TOOL)}
    execute = partial(safe_execute, run=Protected())
    memory = Memory()
    questions = [" ".join(a for a in sys.argv[1:] if a != "--chat") or "Can checkout-api handle 2x traffic?"]
    while questions:
        question = questions.pop()
        result = run_final_agent(c, question, tools, execute, history=memory.messages())
        print(result.model_dump_json(indent=2))
        memory.add(question, result.answer)
        if "--chat" in sys.argv and (nxt := input("\nyou> ").strip()):
            questions.append(nxt)


if __name__ == "__main__":
    main()
