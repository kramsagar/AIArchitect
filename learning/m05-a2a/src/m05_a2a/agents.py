"""Which M4 specialist becomes which A2A agent. Each agent is a separate process/port with its own card and skills.
A skill takes the incident state as a JSON DataPart and returns a partial state update as a data artifact."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentSpec:
    name: str
    port: int
    skills: tuple[str, ...]  # skill id == M4 Crew method name
    description: str
    writes: bool = False  # can this agent change production? (least privilege, M8)


AGENTS: dict[str, AgentSpec] = {
    a.name: a
    for a in (
        AgentSpec("triage-agent", 9101, ("triage",), "Scores SLOs and alerts; decides severity and focus service."),
        AgentSpec(
            "telemetry-agent",
            9102,
            ("metrics", "traces", "logs", "changes"),
            "Read-only investigator over Prometheus, Jaeger, Splunk and the change/chaos feed.",
        ),
        AgentSpec("knowledge-agent", 9103, ("knowledge",), "Hybrid runbook/postmortem retrieval (Module 3)."),
        AgentSpec("rca-agent", 9104, ("rca",), "LLM root-cause analyst; cites evidence ids only."),
        AgentSpec("planner-agent", 9105, ("planner",), "Proposes an allowlisted remediation plan."),
        AgentSpec("executor-agent", 9106, ("executor", "verifier"), "Executes approved plans; verifies.", writes=True),
        AgentSpec("scribe-agent", 9107, ("postmortem",), "Writes the blameless postmortem."),
    )
}


def registry_urls(host: str = "127.0.0.1") -> list[str]:
    return [f"http://{host}:{a.port}" for a in AGENTS.values()]
