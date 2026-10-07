import json
from types import SimpleNamespace

from ocp_analyzer.agent import TOOLS, LLMConfig
from ocp_analyzer.analyzer import run_analysis


class FakeLLM:
    """Scripted OpenAI-compatible client: a list of responses, each a list of tool calls or a final string."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            msg = SimpleNamespace(content=item, tool_calls=None)
        else:
            msg = SimpleNamespace(
                content=None,
                tool_calls=[
                    SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=n, arguments=json.dumps(a)))
                    for i, (n, a) in enumerate(item)
                ],
            )
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_agent_tool_loop(kube, prom, monkeypatch):
    fake = FakeLLM(
        [
            [
                ("get_rule_findings", {}),
                (
                    "get_logs",
                    {
                        "pod": "checkout-service-7d9f8b6c5d-m4qzt",
                        "container": "checkout",
                        "previous": True,
                        "grep": "OutOfMemory",
                    },
                ),
            ],
            [("run_promql", {"query": "sum(rate(container_cpu_usage_seconds_total[5m]))"}), ("nope", {})],
            "### Executive summary\nCPU ceiling.",
        ]
    )
    monkeypatch.setattr(LLMConfig, "client", lambda self: fake)
    steps = []
    report = run_analysis(
        kube, prom, "shop", "checkout-service", llm=LLMConfig(api_key="x", model="m"), on_agent_step=steps.append
    )
    assert report.summary_source == "llm-agent"
    assert report.summary_markdown.startswith("### Executive summary")
    assert [s.tool for s in report.agent_trace] == ["get_rule_findings", "get_logs", "run_promql", "nope"]
    assert "OutOfMemoryError" in report.agent_trace[1].result_preview
    assert "unknown tool" in report.agent_trace[3].result_preview
    assert len(steps) == 4
    tool_msgs = [m for m in fake.requests[-1]["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) == 4
    assert fake.requests[0]["tools"] == TOOLS


def test_agent_failure_falls_back_to_rules(kube, prom, monkeypatch):
    monkeypatch.setattr(LLMConfig, "client", lambda self: FakeLLM([RuntimeError("401 bad key")]))
    report = run_analysis(kube, prom, "shop", "checkout-service", llm=LLMConfig(api_key="x"))
    assert report.summary_source == "rules"
    assert any("401 bad key" in w for w in report.warnings)


def test_agent_forced_final_turn(kube, prom, monkeypatch):
    fake = FakeLLM([[("get_events", {})], "final"])
    monkeypatch.setattr(LLMConfig, "client", lambda self: fake)
    report = run_analysis(kube, prom, "shop", "payment-gateway", llm=LLMConfig(api_key="x", max_steps=2))
    assert report.summary_markdown == "final"
    assert fake.requests[-1]["tool_choice"] == "none"


def test_llm_disabled_without_config(monkeypatch):
    for var in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    assert not LLMConfig.from_env().enabled
    monkeypatch.setenv("OPENAI_BASE_URL", "http://ollama:11434/v1")
    assert LLMConfig.from_env().enabled
