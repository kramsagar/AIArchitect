"""End-to-end pipeline: collect -> derive -> rules -> (agent | rule summary)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .agent import BottleneckAgent, LLMConfig
from .collector import CollectOptions, KubeSource, MetricsSource, build_container_stats, collect
from .logs import analyze_logs
from .models import AgentStep, AnalysisReport
from .report import rule_based_summary
from .rules import RuleContext, Thresholds, health_score, run_rules


def analyze_snapshot(
    snapshot,
    prom: MetricsSource | None = None,
    llm: LLMConfig | None = None,
    thresholds: Thresholds | None = None,
    progress: Callable[[str], None] | None = None,
    on_agent_step: Callable[[AgentStep], None] | None = None,
    llm_client: Any | None = None,
) -> AnalysisReport:
    say = progress or (lambda _m: None)
    say("Deriving container statistics")
    containers = build_container_stats(snapshot)
    insights = analyze_logs(snapshot.logs)
    say("Running bottleneck rules")
    findings = run_rules(RuleContext(snapshot, containers, insights, thresholds or Thresholds()))
    report = AnalysisReport(
        snapshot=snapshot,
        containers=containers,
        findings=findings,
        log_insights=insights,
        health_score=health_score(findings),
        summary_markdown="",
    )
    if llm and (llm.enabled or llm_client):
        say(f"Agent investigating with {llm.model}")
        agent = BottleneckAgent(
            llm, snapshot, containers, findings, insights, prom=prom, client=llm_client, on_step=on_agent_step
        )
        try:
            report.summary_markdown = agent.run()
            report.summary_source = "llm-agent"
            report.llm_model = llm.model
        except Exception as exc:  # noqa: BLE001 - fall back to the deterministic summary
            report.warnings.append(f"LLM agent failed, using rule-based summary: {exc}")
        report.agent_trace = agent.trace
    if not report.summary_markdown:
        report.summary_markdown = rule_based_summary(report)
        report.summary_source = "rules"
    return report


def run_analysis(
    kube: KubeSource,
    prom: MetricsSource | None,
    namespace: str,
    deployment: str,
    options: CollectOptions | None = None,
    llm: LLMConfig | None = None,
    thresholds: Thresholds | None = None,
    progress: Callable[[str], None] | None = None,
    on_agent_step: Callable[[AgentStep], None] | None = None,
) -> AnalysisReport:
    snapshot = collect(kube, prom, namespace, deployment, options, progress)
    return analyze_snapshot(snapshot, prom, llm, thresholds, progress, on_agent_step)
