"""Step 11 - the full M4 crew, every specialist a separate A2A agent (7 agents, 11 skills), orchestrated by the
unchanged M4 LangGraph graph. Approval and checkpoints stay with the orchestrator.

Same as `m05 run --spawn --approve`. With the lab up and Claude:
    m05 --backend live --provider anthropic run --spawn --approve"""

from common import title
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from m05_a2a.agents import registry_urls
from m05_a2a.client import A2AClient
from m05_a2a.launcher import serve_all, stop_all
from m05_a2a.orchestrator import build_remote_graph

servers = serve_all(token="")
try:
    client = A2AClient(registry_urls(), token="")
    app = build_remote_graph(client, InMemorySaver())
    cfg = {"configurable": {"thread_id": "step11"}}
    app.invoke({"alert": "ShopSphereCheckoutLatencySLO"}, cfg)
    plan = app.get_state(cfg).values["plan"]
    title(f"paused for a human: {plan['action']}({plan['target']})")
    v = app.invoke(Command(resume={"approved": True, "by": "you"}), cfg)
    title(f"status={v['status']}  executed={v['executed']}  one trace_id={client.trace_id}")
    for h in client.hops:
        print(f"  {h['agent']:16} {h['skill']:10} {h['ms']:>6} ms")
finally:
    stop_all(servers)
