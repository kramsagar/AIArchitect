import threading
import time

import httpx
import pytest
import uvicorn
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from m05_a2a.agents import AGENTS, AgentSpec, registry_urls
from m05_a2a.client import A2AClient, A2AError, restore_ints
from m05_a2a.launcher import make_crew, serve_all, stop_all
from m05_a2a.orchestrator import build_remote_graph
from m05_a2a.server import build_app


@pytest.fixture(scope="module")
def agents():
    servers = serve_all(token="")
    yield
    stop_all(servers)


def _run(client, approve: bool):
    app = build_remote_graph(client, InMemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}
    app.invoke({"alert": "x"}, cfg)
    assert app.get_state(cfg).next == ("approval",)
    app.invoke(Command(resume={"approved": approve, "by": "test"}), cfg)
    return app.get_state(cfg).values


def test_discovery_indexes_every_skill(agents):
    skills = A2AClient(registry_urls(), token="").discover()
    assert set(skills) == {s for a in AGENTS.values() for s in a.skills}
    assert skills["rca"][0] == "rca-agent"


def test_card_is_spec_shaped(agents):
    card = httpx.get("http://127.0.0.1:9106/.well-known/agent-card.json").json()
    assert card["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
    assert "write" in card["skills"][0]["tags"]


def test_full_incident_over_a2a(agents):
    client = A2AClient(registry_urls(), token="")
    v = _run(client, approve=True)
    assert v["status"] == "recovered"
    assert v["executed"] == ["t1:reset_faults:payments:0"]  # ints restored, not 0.0
    assert {h["agent"] for h in client.hops} == set(AGENTS)
    assert len({h["skill"] for h in client.hops}) == 11


def test_reject_never_calls_executor(agents):
    client = A2AClient(registry_urls(), token="")
    v = _run(client, approve=False)
    assert v["status"] == "rejected"
    assert "executor-agent" not in {h["agent"] for h in client.hops}


def test_unknown_skill_is_rejected(agents):
    client = A2AClient(registry_urls(), token="")
    client.discover()
    client.skills["bogus"] = ("rca-agent", client.skills["rca"][1])
    with pytest.raises(A2AError, match="REJECTED"):
        client.call("bogus", {})
    with pytest.raises(A2AError, match="no agent offers"):
        A2AClient([], token="").call("nothing", {})


def test_bearer_auth_and_traceparent():
    spec = AgentSpec("secure-triage", 9199, ("triage",), "auth test")
    app = build_app(spec, make_crew("fixture", "checkout-latency", "mock"), "http://127.0.0.1:9199", token="s3cret")
    srv = uvicorn.Server(uvicorn.Config(app, port=9199, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    time.sleep(1.0)
    try:
        card = httpx.get("http://127.0.0.1:9199/.well-known/agent-card.json").json()
        assert "Bearer" in card["description"]  # discovery stays public
        with pytest.raises(A2AError, match="unauthorized"):
            A2AClient(["http://127.0.0.1:9199"], token="wrong").call("triage", {})
        ok = A2AClient(["http://127.0.0.1:9199"], token="s3cret")
        assert ok.call("triage", {})["severity"] in {"sev1", "sev2", "sev3", "none"}
    finally:
        srv.should_exit = True


def test_restore_ints():
    assert restore_ints({"a": 1.0, "b": [2.0, 2.5], "c": "x"}) == {"a": 1, "b": [2, 2.5], "c": "x"}
