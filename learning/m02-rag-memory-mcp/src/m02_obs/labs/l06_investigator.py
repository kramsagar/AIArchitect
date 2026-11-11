"""Lab 6 - the investigator end to end: one question per incident scenario, with steps, evidence and grounding.

python -m m02_obs.labs.l06_investigator            # offline mock LLM over fixtures
m02 --backend live --provider anthropic investigate "why is checkout slow?" --trace   # real thing
"""

import asyncio

from mcp.shared.memory import create_connected_server_and_client_session as connect

from m02_obs.agent import Investigator
from m02_obs.config import ObsConfig
from m02_obs.llm import MockInvestigatorLLM
from m02_obs.server import create_server


async def run(scenario: str, question: str) -> None:
    async with connect(create_server(ObsConfig(scenario=scenario))._mcp_server) as session:
        res = await Investigator(MockInvestigatorLLM(), session).run(question)
    inv = res.investigation
    print(f"\n### {scenario}: {question}")
    for s in res.steps:
        print(f"  step {s.step} {s.kind}: {[t.name for t in s.tools]}")
    print(f"  [{inv.status}] {inv.summary}")
    print(f"  evidence sources: {sorted({e.source for e in inv.evidence})}  runbooks: {inv.runbooks}")
    print(f"  llm_calls={res.llm_calls} tool_calls={res.tool_calls} confidence={inv.confidence}")


async def main() -> None:
    await run("checkout-latency", "why is checkout slow?")
    await run("payments-outage", "why are orders failing?")
    await run("healthy", "is anything wrong right now?")
    print("\nExercise: make MockInvestigatorLLM cite a fake trace id and watch ground() drop it.")


if __name__ == "__main__":
    asyncio.run(main())
