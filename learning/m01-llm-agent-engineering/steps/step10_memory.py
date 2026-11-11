"""Step 10 - memory. Concepts: the model is stateless; "memory" = what YOU put back into the context.
Keep only the last N question/answer turns (drop tool chatter) so the context stays small and cheap.

Run:  python steps/step10_memory.py          (scripted 2-turn demo)
      python steps/step10_memory.py --chat   (type your own questions; empty line to quit)
"""

import sys
from collections import deque
from functools import partial

from common import client
from step03_tool_schema import HEALTH_TOOL
from step05_agent_loop import run_agent
from step06_two_tools import CALC_TOOL, SYSTEM6
from step07_tool_errors import safe_execute
from step09_breaker_cache import Protected


class Memory:
    def __init__(self, max_turns: int = 4) -> None:
        self.turns = deque(maxlen=max_turns)  # oldest turns fall off automatically

    def add(self, question: str, answer: str) -> None:
        self.turns.append((question, answer))

    def messages(self) -> list[dict]:
        out = []
        for question, answer in self.turns:
            out += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        return out


def main() -> None:
    c = client()
    tools = {t.name: t for t in (HEALTH_TOOL, CALC_TOOL)}
    execute = partial(safe_execute, run=Protected())
    memory = Memory()

    def turn(question: str) -> None:
        print(f"\nyou> {question}   (history: {len(memory.messages())} messages)")
        answer = run_agent(c, question, tools, SYSTEM6, execute, history=memory.messages())
        print(answer)
        memory.add(question, answer)

    if "--chat" in sys.argv:
        while question := input("\nyou> ").strip():
            turn(question)
        return
    turn("Is checkout-api healthy?")
    turn("Can it handle 2x traffic?")  # "it" only works because turn 1 is in the context
    print("\nTry it without memory: run_agent(c, 'Can it handle 2x traffic?') has no idea what 'it' is.")


if __name__ == "__main__":
    main()
