"""Command line interface: ``ocp-analyzer deployments`` and ``ocp-analyzer analyze``."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from .agent import LLMConfig
from .analyzer import run_analysis
from .collector import CollectOptions
from .connect import Connection, connect
from .demo import DEMO_NAMESPACE
from .report import to_markdown

app = typer.Typer(add_completion=False, help="AIOps bottleneck analyzer for OpenShift deployments.")

ApiUrl = typer.Option("", "--api-url", envvar="OCP_API_URL", help="https://api.<cluster>:6443")
Username = typer.Option("", "--username", "-u", envvar="OCP_USERNAME")
Token = typer.Option("", "--token", envvar="OCP_TOKEN", help="Bearer token instead of username/password")
Namespace = typer.Option(DEMO_NAMESPACE, "--namespace", "-n", envvar="OCP_NAMESPACE")
Insecure = typer.Option(False, "--insecure", help="Skip TLS verification (lab clusters only)")
Demo = typer.Option(False, "--demo", help="Use the built-in synthetic cluster")


def _connect(api_url, username, token, namespace, insecure, demo, prometheus_url=None) -> Connection:
    password = os.getenv("OCP_PASSWORD", "")
    if not demo and not token and username and not password:
        password = typer.prompt("Password", hide_input=True)
    conn = connect(api_url, username, password, token, namespace, not insecure, prometheus_url, demo)
    typer.echo(f"Connected as {conn.user}" + (" (demo)" if conn.demo else ""))
    for note in conn.notes:
        typer.echo(f"  note: {note}", err=True)
    return conn


@app.command()
def deployments(
    api_url: str = ApiUrl,
    username: str = Username,
    token: str = Token,
    namespace: str = Namespace,
    insecure: bool = Insecure,
    demo: bool = Demo,
) -> None:
    """List deployments in a namespace."""
    conn = _connect(api_url, username, token, namespace, insecure, demo)
    for d in conn.kube.list_deployments(namespace):
        st = d.get("status", {})
        typer.echo(f"{d['metadata']['name']:40} {st.get('readyReplicas', 0) or 0}/{d['spec'].get('replicas', 1)} ready")


@app.command()
def analyze(
    deployment: str = typer.Option(..., "--deployment", "-d"),
    api_url: str = ApiUrl,
    username: str = Username,
    token: str = Token,
    namespace: str = Namespace,
    insecure: bool = Insecure,
    demo: bool = Demo,
    prometheus_url: str = typer.Option("", "--prometheus-url", envvar="PROMETHEUS_URL"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write Markdown report"),
    json_output: Path | None = typer.Option(None, "--json", help="Write full JSON report"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip the LLM agent"),
    model: str = typer.Option("", "--model", envvar="LLM_MODEL"),
    log_tail: int = typer.Option(300, "--log-tail"),
    lookback: int = typer.Option(60, "--lookback-minutes"),
) -> None:
    """Collect infra, logs and metrics for a deployment and summarise its bottlenecks."""
    conn = _connect(api_url, username, token, namespace, insecure, demo, prometheus_url)
    llm = None if no_llm else LLMConfig.from_env()
    if llm and model:
        llm.model = model
    report = run_analysis(
        conn.kube,
        conn.prom,
        namespace,
        deployment,
        CollectOptions(log_tail_lines=log_tail, lookback_minutes=lookback),
        llm=llm,
        progress=lambda m: typer.echo(f"- {m}", err=True),
        on_agent_step=lambda s: typer.echo(f"  agent -> {s.tool}({s.arguments})", err=True),
    )
    md = to_markdown(report)
    if output:
        output.write_text(md)
        typer.echo(f"Markdown report written to {output}")
    if json_output:
        json_output.write_text(report.model_dump_json(indent=2))
        typer.echo(f"JSON report written to {json_output}")
    typer.echo("")
    typer.echo(report.summary_markdown)


if __name__ == "__main__":
    app()
