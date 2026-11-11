"""Step 0 - your first LLM call. Concepts: tokens, max_tokens, stop_reason, latency, non-determinism.

Run:  python steps/step00_first_call.py
      python steps/step00_first_call.py "Explain error budgets in 2 lines"
"""

import sys
import time

from common import MODEL, client, text_of


def ask(c, question: str, max_tokens: int = 300):
    started = time.perf_counter()
    resp = c.messages.create(model=MODEL, max_tokens=max_tokens, messages=[{"role": "user", "content": question}])
    return resp, (time.perf_counter() - started) * 1000


def main() -> None:
    question = " ".join(sys.argv[1:]) or "In 3 short bullets: why does p99 latency matter more than average latency?"
    c = client()

    # 1. Tokens: the model reads and bills tokens, not characters. You can count them BEFORE sending.
    counted = c.messages.count_tokens(model=MODEL, messages=[{"role": "user", "content": question}]).input_tokens
    print(f"model={MODEL}  question={len(question)} chars = {counted} input tokens\n")

    # 2. One request -> one response. Everything the model knows is in `messages` (it has no memory between calls).
    resp, ms = ask(c, question)
    print(text_of(resp))
    print(f"\nstop_reason={resp.stop_reason}  input_tokens={resp.usage.input_tokens}  "
          f"output_tokens={resp.usage.output_tokens}  latency={ms:.0f} ms")  # fmt: skip

    # 3. max_tokens caps the OUTPUT. Too small -> stop_reason="max_tokens" and a cut-off answer.
    resp, ms = ask(c, question, max_tokens=12)
    print(f"\nmax_tokens=12 -> stop_reason={resp.stop_reason}: {text_of(resp)!r}")

    print("\nRun this step twice: the wording changes each time (sampling is random).")
    print("Lesson: never parse free text with code. Step 2 makes the model return validated JSON.")


if __name__ == "__main__":
    main()
