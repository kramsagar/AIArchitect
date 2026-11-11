"""Step 9 - auth and trace propagation across a hop.

New idea: the card is public, the skills are not. Calls need `Authorization: Bearer ...` (M8 swaps this for
OAuth2/mTLS). Every call carries a W3C `traceparent` with ONE trace id per incident, so 11 hops on 7 agents
become one trace (M7 exports it to Jaeger)."""

from common import Running, title

from m05_a2a.agents import AgentSpec
from m05_a2a.client import A2AClient, A2AError
from m05_a2a.launcher import make_crew
from m05_a2a.server import build_app

spec = AgentSpec("triage-agent", 9309, ("triage",), "Scores SLOs and alerts.")
app = build_app(spec, make_crew("fixture", "checkout-latency", "mock"), "http://127.0.0.1:9309", token="lab-token")
with Running(app, 9309) as srv:
    for token in ["", "wrong", "lab-token"]:
        c = A2AClient([srv.url], token=token)
        try:
            c.call("triage", {})
            title(f"token={token!r}: OK  trace_id={c.trace_id}")
        except A2AError as e:
            title(f"token={token!r}: {e}")
    print("example traceparent header:", c._headers()["traceparent"])
