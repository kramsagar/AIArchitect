"""Offline tests for the Module 2 step-by-step track (steps/). Forces fixture mode; no lab, no API key."""

import asyncio
import os
import sys
from pathlib import Path

import pytest

os.environ["OBS_BACKEND"] = "fixture"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "steps"))

import step00_promql as s0  # noqa: E402
import step01_resilient_client as s1  # noqa: E402
import step02_jaeger as s2  # noqa: E402
import step03_splunk as s3  # noqa: E402
import step05_chunking as s5  # noqa: E402
import step06_vector_search as s6  # noqa: E402
import step07_retrieval_eval as s7  # noqa: E402
import step08_memory as s8  # noqa: E402
import step09_mcp_server as s9  # noqa: E402
import step11_investigator as s11  # noqa: E402
from m01_agent.errors import ToolError, TransientToolError  # noqa: E402


def test_fixture_backends_answer_offline():
    assert s0.prom_query("anything")["series"]
    assert s2.search_traces("shopsphere-shop", "POST /api/checkout")["traces"]


def test_resilient_client_retries_then_gives_up():
    dead = s1.Backend("http://127.0.0.1:9", timeout_s=0.2, retries=1)
    with pytest.raises(TransientToolError):
        dead.get_json("/x")
    assert dead.calls == 2


def test_jaeger_summarize_finds_slowest_child_and_errors():
    trace = {
        "traceID": "abc",
        "processes": {"p1": {"serviceName": "shop"}, "p2": {"serviceName": "payments"}},
        "spans": [
            {"processID": "p1", "operationName": "POST /api/checkout", "duration": 2_000_000, "references": []},
            {"processID": "p2", "operationName": "authorize", "duration": 1_900_000, "references": [{"r": 1}],
             "tags": [{"key": "error", "value": True}]},
        ],
    }  # fmt: skip
    s = s2.summarize(trace)
    assert s["duration_ms"] == 2000 and s["slowest_spans"][0]["operation"] == "authorize" and s["error_spans"]


@pytest.mark.parametrize(
    "spl", ["index=main | delete", "index=_audit x", "| rest /services", "index=main `macro`", "x=1 | head 1"]
)
def test_spl_guardrail_rejects(spl):
    with pytest.raises(ToolError):
        s3.validate_spl(spl)


def test_spl_guardrail_allows_read_only_search():
    assert s3.validate_spl("search index=main trace_id=abc | stats count by service.name").startswith("index=main")


def test_chunking_ids_and_metadata():
    chunks = s5.chunk_markdown(
        "# T\n## Checkout latency\nShopSphereCheckoutLatencySLO payments slow\n## B\nx", "runbooks"
    )
    assert [c.id for c in chunks] == ["runbooks#checkout-latency", "runbooks#b"]
    assert chunks[0].meta == {"type": "runbook", "alerts": ["ShopSphereCheckoutLatencySLO"], "services": ["payments"]}


def test_vector_search_and_eval_baseline():
    store = s6.VectorStore(s5.load_corpus())
    assert store.search("payments returning 503", k=1)[0][0].id == "runbooks#payments-down"
    assert all(c.meta["type"] == "postmortem" for c, _ in store.search("x", filters={"type": "postmortem"}))
    assert s7.evaluate(store, 3)["recall@k"] >= 0.8


def test_memory_redacts_expires_and_recalls():
    m = s8.LongTermMemory()
    m.remember("k", "password=hunter2 sk-abcdefghijklmnop")
    m.remember("gone", "x", ttl_s=-1)
    assert m.facts() == {"k": "password=[REDACTED] [REDACTED_KEY]"}
    m.record_episode("why is checkout slow?", "payments latency")
    assert m.recall("checkout is slow again")[0]["root_cause"] == "payments latency"
    assert m.recall("is search healthy?") == []


def test_mcp_server_exposes_read_only_tools_resources_prompts():
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    async def run():
        async with connect(s9.mcp._mcp_server) as session:
            tools = (await session.list_tools()).tools
            assert {t.name for t in tools} == {"slo_status", "traces", "logs", "runbooks"}
            assert all(t.annotations.readOnlyHint for t in tools)
            bad = await session.call_tool("logs", {"spl": "index=main | delete"})
            assert bad.isError
            doc = await session.read_resource("runbook://runbooks#checkout-latency")
            assert "checkout" in doc.contents[0].text
            assert (await session.get_prompt("investigate", {"symptom": "x"})).messages

    asyncio.run(run())


def test_ground_drops_invented_evidence():
    inv = s11.Investigation(
        summary="s", status="incident", suspected_cause="payments", recommended_actions=[], confidence="high",
        evidence=[
            s11.Evidence(source="jaeger", ref="7c1e5d0a", finding="slow"),
            s11.Evidence(source="runbook", ref="runbooks#made-up", finding="?"),
            s11.Evidence(source="prometheus", ref="shopsphere:http_errors:ratio_rate5m", finding="ok"),
        ],
    )  # fmt: skip
    grounded, dropped = s11.ground(inv, observed='{"trace_id": "7c1e5d0a"}')
    assert dropped == ["runbooks#made-up"] and len(grounded.evidence) == 2 and grounded.confidence == "low"
