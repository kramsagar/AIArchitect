"""Streamlit UI: connect -> pick deployment -> agentic bottleneck analysis."""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from ocp_analyzer.agent import LLMConfig
from ocp_analyzer.analyzer import run_analysis
from ocp_analyzer.collector import CollectOptions
from ocp_analyzer.connect import connect
from ocp_analyzer.demo import DEMO_API_URL, DEMO_NAMESPACE
from ocp_analyzer.models import AnalysisReport
from ocp_analyzer.report import to_markdown
from ocp_analyzer.utils import fmt_bytes, fmt_cpu, fmt_pct

st.set_page_config(page_title="OCP Bottleneck Analyzer", page_icon="🔎", layout="wide")

SEV_COLOR = {"critical": "#b42318", "high": "#e8590c", "medium": "#f59f00", "low": "#1c7ed6", "info": "#868e96"}
state = st.session_state
state.setdefault("conn", None)
state.setdefault("report", None)
state.setdefault("namespace", "")


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Settings")
    demo = st.toggle("Demo mode (synthetic cluster)", value=os.getenv("DEMO_MODE", "false").lower() == "true")
    st.subheader("LLM agent")
    env_llm = LLMConfig.from_env()
    use_llm = st.checkbox("Use LLM agent for root-cause summary", value=env_llm.enabled)
    provider = st.selectbox(
        "Provider", ["openai", "azure"], index=0 if env_llm.provider != "azure" else 1, disabled=not use_llm
    )
    base_url = st.text_input(
        "Base URL / Azure endpoint",
        value=env_llm.base_url or "",
        placeholder="blank = api.openai.com · http://ollama:11434/v1",
        disabled=not use_llm,
    )
    api_key = st.text_input("API key", value=env_llm.api_key or "", type="password", disabled=not use_llm)
    model = st.text_input("Model / Azure deployment", value=env_llm.model, disabled=not use_llm)
    st.subheader("Collection")
    log_tail = st.slider("Log lines per container", 50, 2000, 300, 50)
    lookback = st.select_slider("Metrics lookback (minutes)", [15, 30, 60, 180, 360], value=60)
    prom_url = st.text_input("Prometheus/Thanos URL override", placeholder="auto-discovered")
    verify_tls = st.checkbox("Verify TLS certificates", value=True)

st.title("🔎 OpenShift Bottleneck Analyzer")
st.caption(
    "Reads the deployment's infra state, events, logs and Prometheus metrics, detects bottlenecks with an "
    "AIOps rule engine and lets an LLM agent investigate and summarise the root cause. Read-only."
)

# ---------------------------------------------------------------- step 1: connect
with st.form("connect"):
    st.subheader("1 · Connect to cluster")
    c1, c2 = st.columns(2)
    api_url = c1.text_input(
        "Cluster API URL", value=DEMO_API_URL if demo else "", placeholder="https://api.cluster.example.com:6443"
    )
    namespace = c2.text_input("Namespace", value=DEMO_NAMESPACE if demo else "")
    c3, c4 = st.columns(2)
    username = c3.text_input("Username", value="demo-user" if demo else "")
    password = c4.text_input("Password", type="password", value="demo" if demo else "")
    with st.expander("Use a bearer token instead"):
        token = st.text_input("Token (oc whoami -t)", type="password")
    submitted = st.form_submit_button("Connect", type="primary")

if submitted:
    state.report = None
    try:
        with st.spinner("Authenticating and discovering Prometheus..."):
            state.conn = connect(api_url, username, password, token, namespace, verify_tls, prom_url or None, demo)
            state.namespace = namespace
            state.deployments = state.conn.kube.list_deployments(namespace)
    except Exception as exc:  # noqa: BLE001
        state.conn = None
        st.error(f"Connection failed: {exc}")

conn = state.conn
if not conn:
    st.info("Enter cluster details (or enable demo mode in the sidebar) and click **Connect**.")
    st.stop()

st.success(
    f"Connected as **{conn.user}** · namespace **{state.namespace}** · "
    f"metrics: **{'Prometheus ' + conn.prom.base_url if conn.prom else 'metrics.k8s.io fallback'}**"
)
for note in conn.notes:
    st.warning(note)

# ---------------------------------------------------------------- step 2: deployment
st.subheader("2 · Select deployment")
deps = state.get("deployments", [])
if not deps:
    st.warning(f"No deployments found in namespace {state.namespace}.")
    st.stop()
labels = {
    f"{d['metadata']['name']}  ({d.get('status', {}).get('readyReplicas', 0) or 0}/"
    f"{d['spec'].get('replicas', 1)} ready)": d["metadata"]["name"]
    for d in deps
}
choice = st.selectbox("Deployment", list(labels))
if st.button("Analyze bottlenecks", type="primary"):
    llm = (
        LLMConfig(api_key=api_key or None, base_url=base_url or None, model=model, provider=provider)
        if use_llm
        else None
    )
    with st.status("Analyzing...", expanded=True) as status:
        try:
            state.report = run_analysis(
                conn.kube,
                conn.prom,
                state.namespace,
                labels[choice],
                CollectOptions(log_tail_lines=log_tail, lookback_minutes=lookback),
                llm=llm,
                progress=st.write,
                on_agent_step=lambda s: st.write(f"🤖 agent called `{s.tool}` {s.arguments or ''}"),
            )
            status.update(label="Analysis complete", state="complete", expanded=False)
        except Exception as exc:  # noqa: BLE001
            status.update(label="Analysis failed", state="error")
            st.error(str(exc))

report: AnalysisReport | None = state.report
if not report:
    st.stop()

# ---------------------------------------------------------------- step 3: results
snap = report.snapshot
st.subheader(f"3 · Results for `{snap.deployment_name}`")
counts = report.severity_counts()
cols = st.columns(6)
cols[0].metric("Health score", f"{report.health_score}/100")
for col, sev in zip(cols[1:], ["critical", "high", "medium", "low", "info"], strict=True):
    col.metric(sev.capitalize(), counts[sev])

tabs = st.tabs(["Summary", "Findings", "Metrics", "Pods & events", "Logs", "Agent trace", "Export"])

with tabs[0]:
    source = f"LLM agent ({report.llm_model})" if report.summary_source == "llm-agent" else "rule engine"
    st.caption(f"Generated by {source}")
    st.markdown(report.summary_markdown)
    for w in report.warnings:
        st.warning(w)

with tabs[1]:
    if not report.findings:
        st.success("No findings.")
    for f in report.findings:
        color = SEV_COLOR[f.severity.value]
        with st.expander(f"[{f.severity.value.upper()}] {f.title} - {f.resource}"):
            st.markdown(
                f"<span style='background:{color};color:white;padding:2px 8px;border-radius:4px'>"
                f"{f.severity.value}</span> &nbsp; category: **{f.category}**",
                unsafe_allow_html=True,
            )
            st.write(f.description)
            for e in f.evidence:
                st.code(e, language=None)
            st.markdown(f"**Recommendation:** {f.recommendation}")


def series_frame(key: str) -> pd.DataFrame:
    rows = [
        {"time": datetime.fromtimestamp(ts), "pod": s["labels"].get("pod", key), "value": v}
        for s in snap.series.get(key, [])
        for ts, v in s["values"]
    ]
    return pd.DataFrame(rows)


with tabs[2]:
    if not snap.series:
        st.info(f"No time series (metrics source: {snap.metrics_source}).")
    charts = [
        ("cpu_usage", "CPU usage (cores)", 1.0),
        ("cpu_throttle_ratio", "CPU throttled periods (%)", 100.0),
        ("memory_working_set", "Memory working set (MiB)", 1 / 2**20),
        ("net_rx_bytes", "Network receive (KiB/s)", 1 / 1024),
    ]
    grid = st.columns(2)
    for i, (key, title, scale) in enumerate(charts):
        df = series_frame(key)
        if df.empty:
            continue
        df["value"] *= scale
        fig = px.line(df, x="time", y="value", color="pod", title=title, height=320)
        limit = next((c.mem_limit for c in report.containers if c.mem_limit), None)
        if key == "memory_working_set" and limit:
            fig.add_hline(y=limit * scale, line_dash="dash", line_color="red", annotation_text="limit")
        cpu_limit = next((c.cpu_limit for c in report.containers if c.cpu_limit), None)
        if key == "cpu_usage" and cpu_limit:
            fig.add_hline(y=cpu_limit, line_dash="dash", line_color="red", annotation_text="limit")
        fig.update_layout(legend={"orientation": "h", "y": -0.25}, margin={"t": 40, "b": 0})
        grid[i % 2].plotly_chart(fig, width="stretch")
    latency = snap.instant.get("http_p95_latency")
    if latency:
        st.metric("HTTP p95 latency", f"{latency[0]['value']:.2f}s")

with tabs[3]:
    st.markdown("**Containers**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "pod": c.pod,
                    "container": c.container,
                    "node": c.node,
                    "phase": c.phase,
                    "state": c.state_reason or c.state,
                    "ready": c.ready,
                    "restarts": c.restarts,
                    "last termination": c.last_termination_reason,
                    "cpu use/req/lim": f"{fmt_cpu(c.cpu_usage)}/{fmt_cpu(c.cpu_request)}/{fmt_cpu(c.cpu_limit)}",
                    "throttled": fmt_pct(c.throttle_ratio),
                    "mem use/lim": f"{fmt_bytes(c.mem_usage)}/{fmt_bytes(c.mem_limit)}",
                    "mem % limit": fmt_pct(c.mem_limit_util),
                }
                for c in report.containers
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    st.markdown("**Events**")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "type": e.get("type"),
                    "reason": e.get("reason"),
                    "object": (e.get("involvedObject") or {}).get("name"),
                    "count": e.get("count"),
                    "last seen": e.get("lastTimestamp") or e.get("eventTime"),
                    "message": e.get("message"),
                }
                for e in snap.events
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    if snap.hpa:
        st.markdown("**HorizontalPodAutoscaler**")
        st.json({"spec": snap.hpa.get("spec"), "status": snap.hpa.get("status")}, expanded=False)

with tabs[4]:
    insights = [li for li in report.log_insights if li.lines]
    if not insights:
        st.info("No logs collected.")
    for li in insights:
        title = f"{li.pod}/{li.container}{' (previous instance)' if li.previous else ''} - {li.lines} lines"
        with st.expander(title, expanded=bool(li.category_counts)):
            if li.category_counts:
                st.bar_chart(pd.Series(li.category_counts, name="lines"))
                st.markdown("**Top error templates**")
                st.dataframe(pd.DataFrame(li.top_templates), hide_index=True, width="stretch")
            else:
                st.success("No error patterns detected.")
            key = f"{li.pod}/{li.container}" + ("#previous" if li.previous else "")
            st.code("\n".join(snap.logs.get(key, "").splitlines()[-50:]), language=None)

with tabs[5]:
    if not report.agent_trace:
        st.info("The LLM agent was not used. Enable it in the sidebar to see its tool-calling trace.")
    for s in report.agent_trace:
        with st.expander(f"Step {s.step}: {s.tool}({', '.join(f'{k}={v}' for k, v in s.arguments.items())})"):
            st.code(s.result_preview, language="json")

with tabs[6]:
    name = f"bottleneck-{snap.namespace}-{snap.deployment_name}"
    st.download_button("Download Markdown report", to_markdown(report), f"{name}.md", "text/markdown")
    st.download_button("Download JSON report", report.model_dump_json(indent=2), f"{name}.json", "application/json")
    if snap.warnings:
        st.markdown("**Collection warnings**")
        for w in snap.warnings:
            st.caption(w)
