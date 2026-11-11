import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from m04_crew.checkpoint import open_checkpointer
from m04_crew.crew import Crew
from m04_crew.graph import build_graph
from m04_crew.llm import MockCrewLLM
from m04_crew.state import merge_evidence
from m04_crew.supervisor import build_supervisor_graph
from m04_crew.tools import Toolbox


def crew(scenario="checkout-latency", **kw):
    return Crew(Toolbox("fixture", scenario), MockCrewLLM(), **kw)


def start(c, saver=None, thread="t"):
    app = build_graph(c, checkpointer=saver or InMemorySaver())
    cfg = {"configurable": {"thread_id": thread}}
    app.invoke({"alert": "test"}, cfg)
    return app, cfg


def test_reducer_dedupes_by_id():
    a = [{"id": "x", "source": "s", "summary": "1"}]
    assert merge_evidence(
        a, [{"id": "x", "source": "s", "summary": "2"}, {"id": "y", "source": "s", "summary": ""}]
    ) == [
        {"id": "x", "source": "s", "summary": "2"},
        {"id": "y", "source": "s", "summary": ""},
    ]


def test_healthy_stops_after_triage():
    c = crew("healthy")
    app, cfg = start(c)
    s = app.get_state(cfg)
    assert not s.next and s.values["status"] == "no_incident" and c.llm.calls == 0


def test_pauses_for_approval_before_any_write():
    c = crew()
    app, cfg = start(c)
    s = app.get_state(cfg)
    assert s.next == ("approval",) and s.tasks[0].interrupts
    assert s.values["plan"]["action"] == "reset_faults" and s.values["plan"]["target"] == "payments"
    assert c.tools.writes == []
    sources = {e["source"] for e in s.values["evidence"]}
    assert {"metrics", "traces", "logs", "changes", "runbooks"} <= sources


def test_approve_executes_once_and_recovers():
    c = crew()
    app, cfg = start(c)
    final = app.invoke(Command(resume={"approved": True, "by": "alice"}), cfg)
    assert final["status"] == "recovered" and len(c.tools.writes) == 1
    assert final["postmortem"].startswith("# Postmortem") and "alice" in final["postmortem"]
    assert set(final["rca"]["evidence_ids"]) <= {e["id"] for e in final["evidence"]}


def test_reject_never_executes():
    c = crew("payments-outage")
    app, cfg = start(c)
    final = app.invoke(Command(resume={"approved": False, "by": "bob"}), cfg)
    assert final["status"] == "rejected" and c.tools.writes == [] and final["postmortem"]


def test_crash_before_verifier_resumes_without_repeating_executor(tmp_path):
    c = crew(crash_before="verifier")
    with open_checkpointer(str(tmp_path / "cp.db")) as saver:
        app, cfg = start(c, saver)
        with pytest.raises(RuntimeError):
            app.invoke(Command(resume={"approved": True}), cfg)
        assert app.get_state(cfg).next == ("verifier",)
        app.invoke(None, cfg)
        final = app.get_state(cfg).values
    assert final["status"] == "recovered" and len(c.tools.writes) == 1 and len(final["executed"]) == 1


def test_policy_refuses_reset_without_active_fault():
    class Bad(MockCrewLLM):
        def complete(self, system, user, max_tokens=600):
            if "[plan]" in system:
                self.calls += 1
                return '{"action": "reset_faults", "target": "shop", "rationale": "x"}'
            return super().complete(system, user, max_tokens)

    c = Crew(Toolbox("fixture", "checkout-latency"), Bad())
    app, cfg = start(c)
    s = app.get_state(cfg)
    assert s.values["plan"]["action"] == "escalate" and s.values["status"] == "escalated" and not s.next


def test_rca_drops_invented_evidence():
    class Liar(MockCrewLLM):
        def complete(self, system, user, max_tokens=600):
            if "[rca]" in system:
                self.calls += 1
                return (
                    '{"root_cause": "made up cause", "service": "x", "confidence": "high", '
                    '"evidence_ids": ["trace:nope"]}'
                )
            return super().complete(system, user, max_tokens)

    app, cfg = start(Crew(Toolbox("fixture", "checkout-latency"), Liar()))
    rca = app.get_state(cfg).values["rca"]
    assert rca["evidence_ids"] == [] and rca["confidence"] == "low"


def test_executor_tool_is_idempotent_and_allowlisted():
    tb = Toolbox("fixture", "payments-outage")
    assert tb.reset_faults("payments", "k1")["result"] != "already done"
    assert tb.reset_faults("payments", "k1")["result"] == "already done"
    with pytest.raises(ValueError):
        tb.reset_faults("database", "k2")


def test_supervisor_bounded_and_ends_with_rca():
    c = crew()
    out = build_supervisor_graph(c, max_turns=7).invoke({"alert": "t"})
    agents = [t["agent"] for t in out["timeline"] if t["agent"] != "supervisor"]
    assert agents[-1] == "rca" and len(agents) <= 8 and out["rca"]["confidence"] == "high"
