"""Lab 6 - the agent loop, step by step: Observe -> Decide -> Act -> Observe.

Run: python -m m01_agent.labs.l06_agent_loop  (add --provider openai via the CLI for a real model)"""

from __future__ import annotations

from ..factory import build_agent


def main() -> None:
    agent = build_agent()
    question = "Can checkout-api handle 2x traffic?"
    print(f"USER: {question}\n")
    result = agent.run(question)
    for s in result.steps:
        if s.decision == "tool_calls":
            print(f"[step {s.step}] DECIDE: call {[c.name for c in s.tool_calls]}")
            for c, o in zip(s.tool_calls, s.observations, strict=True):
                print(f"          ACT:     {c.name}({c.arguments})")
                print(f"          OBSERVE: ok={o.ok} {str(o.output or o.error)[:120]}...")
        else:
            print(f"[step {s.step}] DECIDE: final answer ({s.decision})")
    print("\nFINAL (validated AssistantResponse):")
    print(result.response.model_dump_json(indent=2))
    print(f"\nusage: {result.usage.model_dump()}")
    print(
        "\nNote the 2-hop plan: the replicas calculation used numbers OBSERVED in step 1 - that dependency is\n"
        "why this is an agent loop and not a single prompt."
    )


if __name__ == "__main__":
    main()
