import asyncio
import json

from m01_agent.llm.base import LLMDecision
from mcp.shared.memory import create_connected_server_and_client_session as connect

from m02_obs.agent import Investigator, ground
from m02_obs.config import ObsConfig
from m02_obs.llm import MockInvestigatorLLM
from m02_obs.memory import LongTermMemory, SessionMemory
from m02_obs.schemas import Evidence, Investigation
from m02_obs.server import create_server


def run_with_session(scenario, fn):
    async def main():
        async with connect(create_server(ObsConfig(scenario=scenario))._mcp_server) as s:
            return await fn(s)

    return asyncio.run(main())


def test_server_exposes_read_only_tools_resources_prompts():
    async def check(s):
        tools = (await s.list_tools()).tools
        assert len(tools) == 8 and all(t.annotations.readOnlyHint for t in tools)
        bad = await s.call_tool("search_logs", {"query": "index=main | delete"})
        assert bad.isError and "not allowed" in bad.content[0].text
        rb = await s.read_resource("runbook://runbooks#payments-down")
        assert "ShopSpherePaymentsErrors" in rb.contents[0].text
        prompt = await s.get_prompt("investigate", {"symptom": "ShopSphereHighP99"})
        assert "ShopSphereHighP99" in prompt.messages[0].content.text

    run_with_session("healthy", check)


def investigate(scenario, question="why is checkout slow?", ltm=None):
    async def go(s):
        return await Investigator(MockInvestigatorLLM(), s, session_memory=SessionMemory(), long_term=ltm).run(question)

    return run_with_session(scenario, go)


def test_latency_incident_names_payments_with_grounded_evidence():
    res = investigate("checkout-latency")
    inv = res.investigation
    assert res.status == "completed" and inv.status == "incident"
    assert "payment-provider.authorize" in inv.suspected_cause
    assert {e.source for e in inv.evidence} >= {"prometheus", "jaeger", "splunk", "runbook", "changes"}
    assert "runbooks#checkout-latency" in inv.runbooks
    assert res.dropped_evidence == []
    assert res.steps[0].tools and len(res.steps[0].tools) == 3  # broad tools ran in parallel


def test_payments_outage_and_healthy():
    out = investigate("payments-outage").investigation
    assert "payments-service" in out.affected_services and "failing" in out.suspected_cause
    ok = investigate("healthy")
    assert ok.investigation.status == "healthy" and ok.tool_calls == 3


def test_episodic_memory_is_recalled_next_time(tmp_path):
    ltm = LongTermMemory(tmp_path / "m.db")
    investigate("checkout-latency", ltm=ltm)
    second = investigate("checkout-latency", "checkout is slow again", ltm=ltm)
    assert second.recalled_episodes


def test_ground_drops_invented_citations():
    inv = Investigation(
        summary="s", status="incident", affected_services=[], suspected_cause="x", confidence="high",
        evidence=[Evidence(source="jaeger", ref="deadbeefdeadbeefdeadbeefdeadbeef", finding="made up"),
                  Evidence(source="prometheus", ref="shopsphere:http_latency_seconds:p95_5m", finding="real")],
        recommended_actions=[], runbooks=["runbooks#invented"],
    )  # fmt: skip
    fixed, dropped = ground(inv, {"prometheus": '{"p95_ms": 2050}'})
    assert dropped == ["jaeger:deadbeefdeadbeefdeadbeefdeadbeef"]
    assert fixed.runbooks == [] and fixed.confidence == "medium"


class BadThenGood:
    def __init__(self):
        self.n = 0

    def decide(self, messages, tools, *, timeout_s):
        self.n += 1
        if self.n == 1:
            return LLMDecision(content='{"summary": "oops"}', prompt_tokens=1, completion_tokens=1)
        inv = Investigation(summary="ok", status="unknown", affected_services=[], suspected_cause=None,
                            evidence=[], recommended_actions=[], runbooks=[], confidence="low")  # fmt: skip
        assert "did not match the schema" in messages[-1]["content"]
        return LLMDecision(content=inv.model_dump_json(), prompt_tokens=1, completion_tokens=1)


def test_invalid_output_is_repaired():
    res = run_with_session("healthy", lambda s: Investigator(BadThenGood(), s).run("status?"))
    assert res.status == "completed" and [s.kind for s in res.steps] == ["invalid_output", "final"]
    assert json.loads(res.model_dump_json())["llm_calls"] == 2
