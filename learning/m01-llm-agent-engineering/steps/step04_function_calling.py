"""Step 4 - function calling, one round trip. Concepts: tool_use block, tool_result, the 2-request pattern.

Run:  python steps/step04_function_calling.py
      python steps/step04_function_calling.py "How is payments-gateway doing?"
"""

import json
import sys

from common import MODEL, client, text_of
from step03_tool_schema import HEALTH_TOOL


def main() -> None:
    question = " ".join(sys.argv[1:]) or "Is checkout-api healthy right now?"
    c = client()
    messages = [{"role": "user", "content": question}]

    # Request 1: question + tool spec. The model decides whether it needs the tool.
    resp = c.messages.create(model=MODEL, max_tokens=600, tools=[HEALTH_TOOL.spec()], messages=messages)
    print(f"request 1 -> stop_reason={resp.stop_reason}")
    for block in resp.content:
        print("   block:", block.type, block.input if block.type == "tool_use" else getattr(block, "text", "")[:80])
    if resp.stop_reason != "tool_use":
        print("The model answered without a tool.")
        return

    # We execute the call ourselves.
    call = next(b for b in resp.content if b.type == "tool_use")
    result = HEALTH_TOOL.run(call.input)
    print(f"we ran {call.name}({call.input}) -> {result}")

    # Request 2: the SAME history + the model's tool call + our result (linked by tool_use_id).
    messages.append({"role": "assistant", "content": resp.content})
    messages.append(
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": call.id, "content": json.dumps(result)}]}
    )
    resp = c.messages.create(model=MODEL, max_tokens=600, tools=[HEALTH_TOOL.spec()], messages=messages)
    print(f"\nrequest 2 -> stop_reason={resp.stop_reason}\n")
    print(text_of(resp))
    print(f"\nmessages sent in request 2: {len(messages)} (user, assistant tool_use, user tool_result)")


if __name__ == "__main__":
    main()
