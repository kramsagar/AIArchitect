"""Step 5 - the agent loop. Concepts: Observe -> Decide -> Act -> Observe, repeated; max_steps guard.
Step 4 hard-coded one round trip. Now a loop runs until the model stops asking for tools.

Run:  python steps/step05_agent_loop.py
      python steps/step05_agent_loop.py "Compare checkout-api and search-api"
"""

import json
import sys

from common import MODEL, client, text_of
from step03_tool_schema import HEALTH_TOOL

SYSTEM = (
    "You are SRE Copilot, a read-only reliability assistant. Use tools for facts and never invent numbers. "
    "Independent lookups can be requested together in one step. Answer in at most 4 short bullets."
)
TOOLS = {HEALTH_TOOL.name: HEALTH_TOOL}


def execute(call, tools: dict) -> dict:
    """ACT: run one tool call and wrap the result for the model (step 7 makes this safe)."""
    result = tools[call.name].run(call.input)
    return {"type": "tool_result", "tool_use_id": call.id, "content": json.dumps(result)}


def run_agent(c, question, tools=TOOLS, system=SYSTEM, execute=execute, max_steps=6, history=None, trace=True):
    messages = list(history or []) + [{"role": "user", "content": question}]  # OBSERVE: the context
    for step in range(1, max_steps + 1):
        resp = c.messages.create(  # DECIDE
            model=MODEL,
            max_tokens=1000,
            system=system,
            tools=[t.spec() for t in tools.values()],
            messages=messages,
        )
        calls = [b for b in resp.content if b.type == "tool_use"]
        if not calls:  # no tool requested -> this is the final answer
            if trace:
                print(f"[step {step}] decide -> final answer")
            return text_of(resp)
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for call in calls:  # ACT (every call the model asked for in this step)
            result = execute(call, tools)
            if trace:
                print(f"[step {step}] act {call.name}({json.dumps(call.input)}) -> {result['content'][:90]}")
            results.append(result)
        messages.append({"role": "user", "content": results})  # OBSERVE: results go back into the context
    return f"Stopped: no final answer within {max_steps} steps."  # guard: never loop forever


def main() -> None:
    question = " ".join(sys.argv[1:]) or "Compare the health of checkout-api and search-api. Which one needs attention?"
    print("\n" + run_agent(client(), question))


if __name__ == "__main__":
    main()
