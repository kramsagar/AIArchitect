"""Step 7 - wrap a real M4 specialist (triage) as an A2A agent: `m05_a2a.server.build_app`.

New idea: SpecialistExecutor maps skill id -> Crew method. The agent is stateless between calls: the caller
sends the incident state, the agent returns a partial update, LangGraph reducers merge it (exactly like M4)."""

from common import Running, rpc, title

from m05_a2a.agents import AgentSpec
from m05_a2a.launcher import make_crew
from m05_a2a.server import build_app

spec = AgentSpec("triage-agent", 9307, ("triage",), "Scores SLOs and alerts.")
app = build_app(spec, make_crew("fixture", "checkout-latency", "mock"), "http://127.0.0.1:9307", token="")
msg = {"message": {"role": "ROLE_USER", "messageId": "m1", "parts": [{"data": {"skill": "triage", "state": {}}}]}}

with Running(app, 9307) as srv:
    task = rpc(srv.url + "/a2a/jsonrpc", "SendMessage", msg)["result"]["task"]
    update = task["artifacts"][0]["parts"][0]["data"]["update"]
    title(task["status"]["state"])
    print({k: update[k] for k in ("severity", "focus_service", "symptom")})
    bad = {"message": {**msg["message"], "messageId": "m2", "parts": [{"data": {"skill": "executor"}}]}}
    title("asking triage-agent to run the executor skill (least privilege)")
    print(rpc(srv.url + "/a2a/jsonrpc", "SendMessage", bad)["result"]["task"]["status"]["state"])
