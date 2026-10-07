"""Deterministic AIOps rule engine that turns a snapshot into ranked bottleneck findings."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from .models import ContainerStats, Finding, LogInsight, Severity, Snapshot
from .utils import fmt_bytes, fmt_cpu, fmt_pct, parse_cpu, parse_memory


@dataclass
class Thresholds:
    mem_limit_warn: float = 0.80
    mem_limit_crit: float = 0.90
    cpu_throttle_warn: float = 0.10
    cpu_throttle_crit: float = 0.25
    cpu_limit_crit: float = 0.90
    cpu_over_request: float = 1.5
    restart_warn: int = 3
    overprovisioned_ratio: float = 0.20
    latency_p95_warn_s: float = 1.0
    node_util_warn: float = 0.85
    quota_warn: float = 0.90
    imbalance_ratio: float = 3.0
    net_drops_warn: float = 1.0
    probe_failures_high: int = 10


@dataclass
class RuleContext:
    snapshot: Snapshot
    containers: list[ContainerStats]
    log_insights: list[LogInsight]
    thresholds: Thresholds = field(default_factory=Thresholds)

    def instant(self, key: str) -> list[dict]:
        return self.snapshot.instant.get(key, [])


Rule = Callable[[RuleContext], list[Finding]]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


def _ref(c: ContainerStats) -> str:
    return f"pod/{c.pod} container/{c.container}"


def _event_count(e: dict) -> int:
    return int(e.get("count") or (e.get("series") or {}).get("count") or 1)


@rule
def oom_killed(ctx: RuleContext) -> list[Finding]:
    out = []
    for c in ctx.containers:
        if "OOMKilled" not in (c.last_termination_reason, c.state_reason):
            continue
        out.append(
            Finding(
                rule_id="oom_killed",
                title="Container killed by the kernel OOM killer",
                severity=Severity.CRITICAL,
                category="memory",
                resource=_ref(c),
                description="The container exceeded its memory limit and was OOMKilled, causing restarts "
                "and dropped in-flight requests.",
                evidence=[
                    f"last termination reason: OOMKilled (exit code {c.last_termination_exit_code})",
                    f"restarts: {c.restarts}",
                    f"memory limit: {fmt_bytes(c.mem_limit)}, working set now: {fmt_bytes(c.mem_usage)}, "
                    f"1h peak: {fmt_bytes(c.mem_max)}",
                ],
                recommendation="Raise the memory limit to ~1.3x the observed peak, or fix the leak. For JVMs "
                "set -XX:MaxRAMPercentage=75 so the heap respects the container limit.",
            )
        )
    return out


@rule
def crash_looping(ctx: RuleContext) -> list[Finding]:
    out = []
    for c in ctx.containers:
        if c.state_reason == "CrashLoopBackOff":
            sev = Severity.CRITICAL
        elif c.restarts >= ctx.thresholds.restart_warn:
            sev = Severity.HIGH
        else:
            continue
        out.append(
            Finding(
                rule_id="crash_looping",
                title="Container is restarting repeatedly",
                severity=sev,
                category="availability",
                resource=_ref(c),
                description="Frequent restarts reduce serving capacity and usually indicate a crash, failed "
                "liveness probe or resource kill.",
                evidence=[
                    f"state: {c.state} ({c.state_reason or '-'})",
                    f"restarts total: {c.restarts}"
                    + (f", last hour: {c.restarts_1h:.0f}" if c.restarts_1h is not None else ""),
                    f"last termination: {c.last_termination_reason or '-'} (exit {c.last_termination_exit_code})",
                ],
                recommendation="Inspect the previous container logs (`oc logs --previous`) and termination "
                "reason; fix the startup failure or relax the liveness probe.",
            )
        )
    return out


@rule
def image_or_config_errors(ctx: RuleContext) -> list[Finding]:
    bad = {"ImagePullBackOff", "ErrImagePull", "InvalidImageName", "CreateContainerConfigError"}
    return [
        Finding(
            rule_id="container_start_failure",
            title=f"Container cannot start: {c.state_reason}",
            severity=Severity.CRITICAL,
            category="availability",
            resource=_ref(c),
            description="The container never starts, so the pod contributes no capacity.",
            evidence=[f"waiting reason: {c.state_reason}"],
            recommendation="Verify image name/tag, pull secret and referenced ConfigMaps/Secrets.",
        )
        for c in ctx.containers
        if c.state_reason in bad
    ]


@rule
def memory_saturation(ctx: RuleContext) -> list[Finding]:
    t, out = ctx.thresholds, []
    for c in ctx.containers:
        util = c.mem_limit_util
        if util is None or util < t.mem_limit_warn or c.last_termination_reason == "OOMKilled":
            continue
        out.append(
            Finding(
                rule_id="memory_saturation",
                title="Memory close to limit",
                severity=Severity.HIGH if util >= t.mem_limit_crit else Severity.MEDIUM,
                category="memory",
                resource=_ref(c),
                description="Working set is close to the memory limit; the container is at risk of OOMKill "
                "and may already be spending time in GC / page reclaim.",
                evidence=[
                    f"memory peak/limit: {fmt_bytes(max(c.mem_usage or 0, c.mem_max or 0))} / "
                    f"{fmt_bytes(c.mem_limit)} ({fmt_pct(util)})"
                ],
                recommendation="Increase the memory limit or reduce footprint (caches, heap size, batch sizes).",
            )
        )
    return out


@rule
def cpu_throttling(ctx: RuleContext) -> list[Finding]:
    t, out = ctx.thresholds, []
    for c in ctx.containers:
        r = c.throttle_ratio
        if r is None or r < t.cpu_throttle_warn:
            continue
        out.append(
            Finding(
                rule_id="cpu_throttling",
                title="CPU throttled by CFS quota",
                severity=Severity.HIGH if r >= t.cpu_throttle_crit else Severity.MEDIUM,
                category="cpu",
                resource=_ref(c),
                description="The kernel is pausing the container because it hits its CPU limit, which shows "
                "up as tail latency even when average CPU looks fine.",
                evidence=[
                    f"throttled periods: {fmt_pct(r)}",
                    f"cpu usage {fmt_cpu(c.cpu_usage)} / limit {fmt_cpu(c.cpu_limit)}",
                ],
                recommendation="Raise or remove the CPU limit (keep a realistic request), or scale out. Check "
                "thread-pool sizing against the CPU limit.",
            )
        )
    return out


@rule
def cpu_saturation(ctx: RuleContext) -> list[Finding]:
    t, out = ctx.thresholds, []
    for c in ctx.containers:
        if c.cpu_usage is None:
            continue
        if c.cpu_limit_util is not None and c.cpu_limit_util >= t.cpu_limit_crit:
            out.append(
                Finding(
                    rule_id="cpu_saturation",
                    title="CPU usage at limit",
                    severity=Severity.HIGH,
                    category="cpu",
                    resource=_ref(c),
                    description="The container is consuming nearly all of its CPU limit.",
                    evidence=[
                        f"cpu {fmt_cpu(c.cpu_usage)} / limit {fmt_cpu(c.cpu_limit)} ({fmt_pct(c.cpu_limit_util)})"
                    ],
                    recommendation="Scale horizontally (HPA) or raise the CPU limit; profile hot code paths.",
                )
            )
        elif c.cpu_request_util is not None and c.cpu_request_util >= t.cpu_over_request:
            out.append(
                Finding(
                    rule_id="cpu_over_request",
                    title="CPU usage well above request",
                    severity=Severity.MEDIUM,
                    category="cpu",
                    resource=_ref(c),
                    description="Usage exceeds the request, so the scheduler under-estimates this pod and it "
                    "competes for spare node CPU; HPA utilisation will also read high.",
                    evidence=[
                        f"cpu {fmt_cpu(c.cpu_usage)} / request {fmt_cpu(c.cpu_request)} ({fmt_pct(c.cpu_request_util)})"
                    ],
                    recommendation="Right-size the CPU request to the observed p95 usage.",
                )
            )
    return out


@rule
def missing_resources(ctx: RuleContext) -> list[Finding]:
    out = []
    for c in ctx.containers:
        missing = [
            n
            for n, v in (
                ("cpu request", c.cpu_request),
                ("memory request", c.mem_request),
                ("memory limit", c.mem_limit),
            )
            if v is None
        ]
        if not missing:
            continue
        no_requests = c.cpu_request is None and c.mem_request is None
        out.append(
            Finding(
                rule_id="missing_resources",
                title="Resource requests/limits not set",
                severity=Severity.MEDIUM if no_requests else Severity.LOW,
                category="config",
                resource=_ref(c),
                description="Without requests the pod is BestEffort/Burstable: it is evicted first under node "
                "pressure and the scheduler cannot place it sensibly.",
                evidence=[f"missing: {', '.join(missing)}"],
                recommendation="Set requests from observed usage and a memory limit; consider a LimitRange.",
            )
        )
    return out


@rule
def overprovisioned(ctx: RuleContext) -> list[Finding]:
    t, out = ctx.thresholds, []
    for c in ctx.containers:
        if c.phase != "Running" or c.cpu_request_util is None or c.mem_request_util is None:
            continue
        if c.cpu_request_util < t.overprovisioned_ratio and c.mem_request_util < t.overprovisioned_ratio:
            out.append(
                Finding(
                    rule_id="overprovisioned",
                    title="Over-provisioned requests (cost)",
                    severity=Severity.INFO,
                    category="capacity",
                    resource=_ref(c),
                    description="Requests are far above actual usage, reserving capacity that other "
                    "workloads cannot use.",
                    evidence=[
                        f"cpu {fmt_cpu(c.cpu_usage)} / request {fmt_cpu(c.cpu_request)}",
                        f"memory {fmt_bytes(c.mem_usage)} / request {fmt_bytes(c.mem_request)}",
                    ],
                    recommendation="Lower requests towards p95 usage (+headroom) or enable VPA in recommend mode.",
                )
            )
    return out


@rule
def replicas_unavailable(ctx: RuleContext) -> list[Finding]:
    dep = ctx.snapshot.deployment
    spec, status = dep.get("spec", {}), dep.get("status", {})
    desired = spec.get("replicas", 1)
    available = status.get("availableReplicas", 0) or 0
    out = []
    if desired and available < desired:
        out.append(
            Finding(
                rule_id="replicas_unavailable",
                title=f"Only {available}/{desired} replicas available",
                severity=Severity.CRITICAL if available == 0 else Severity.HIGH,
                category="availability",
                resource=f"deployment/{ctx.snapshot.deployment_name}",
                description="The deployment is running below its desired capacity.",
                evidence=[
                    f"desired={desired} ready={status.get('readyReplicas', 0)} available={available} "
                    f"unavailable={status.get('unavailableReplicas', desired - available)}"
                ],
                recommendation="See pod-level findings (scheduling, crashes, probes) for the cause.",
            )
        )
    for cond in status.get("conditions", []):
        if cond.get("reason") == "ProgressDeadlineExceeded":
            out.append(
                Finding(
                    rule_id="rollout_stuck",
                    title="Rollout exceeded its progress deadline",
                    severity=Severity.HIGH,
                    category="availability",
                    resource=f"deployment/{ctx.snapshot.deployment_name}",
                    description="The latest ReplicaSet never became available.",
                    evidence=[cond.get("message", "")],
                    recommendation="Check the new ReplicaSet's pods; roll back with `oc rollout undo` if needed.",
                )
            )
    if desired == 1 and not ctx.snapshot.hpa:
        out.append(
            Finding(
                rule_id="single_replica",
                title="Single replica without autoscaling",
                severity=Severity.LOW,
                category="capacity",
                resource=f"deployment/{ctx.snapshot.deployment_name}",
                description="One pod is both a capacity bottleneck and a single point of failure.",
                evidence=["spec.replicas=1, no HPA"],
                recommendation="Run >=2 replicas with a PodDisruptionBudget, or add an HPA.",
            )
        )
    return out


@rule
def pending_pods(ctx: RuleContext) -> list[Finding]:
    sched = defaultdict(list)
    for e in ctx.snapshot.events:
        if e.get("reason") == "FailedScheduling":
            sched[(e.get("involvedObject") or {}).get("name")].append(e.get("message", ""))
    out = []
    for pod in ctx.snapshot.pods:
        if pod.get("status", {}).get("phase") != "Pending":
            continue
        name = pod["metadata"]["name"]
        msgs = sched.get(name, [])
        if not msgs and any(c.state_reason for c in ctx.containers if c.pod == name):
            continue
        out.append(
            Finding(
                rule_id="pending_pod",
                title="Pod cannot be scheduled",
                severity=Severity.HIGH,
                category="scheduling",
                resource=f"pod/{name}",
                description="The pod is Pending, so requested capacity is not being delivered.",
                evidence=msgs[:2] or ["phase=Pending with no scheduling event"],
                recommendation="Free or add node capacity (MachineSet/cluster-autoscaler), reduce requests, or "
                "relax node selectors/affinity/taints.",
            )
        )
    return out


@rule
def probe_failures(ctx: RuleContext) -> list[Finding]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for e in ctx.snapshot.events:
        if e.get("reason") == "Unhealthy":
            grouped[(e.get("involvedObject") or {}).get("name", "?")].append(e)
    out = []
    for pod, events in grouped.items():
        total = sum(_event_count(e) for e in events)
        kinds = sorted({e.get("message", "").split(" probe")[0] for e in events})
        out.append(
            Finding(
                rule_id="probe_failures",
                title=f"{'/'.join(kinds)} probe failures",
                severity=Severity.HIGH if total >= ctx.thresholds.probe_failures_high else Severity.MEDIUM,
                category="availability",
                resource=f"pod/{pod}",
                description="Failing readiness probes remove the pod from the Service; failing liveness probes "
                "restart it. Under load this often means the app is too slow to answer health checks.",
                evidence=[f"{total} probe failure events", events[0].get("message", "")[:200]],
                recommendation="Check whether probes time out under load; increase timeoutSeconds, use a "
                "lightweight health endpoint, and add a startupProbe for slow starts.",
            )
        )
    return out


@rule
def warning_events(ctx: RuleContext) -> list[Finding]:
    handled = {"Unhealthy", "FailedScheduling", "BackOff", "Failed", "Pulling", "Killing"}
    severe = {"FailedMount", "FailedAttachVolume", "Evicted", "OOMKilling", "NodeNotReady", "FailedCreate"}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for e in ctx.snapshot.events:
        if e.get("type") == "Warning" and e.get("reason") not in handled:
            grouped[e.get("reason", "Unknown")].append(e)
    return [
        Finding(
            rule_id="warning_events",
            title=f"Warning events: {reason}",
            severity=Severity.HIGH if reason in severe else Severity.MEDIUM,
            category="events",
            resource=", ".join(
                sorted(
                    {
                        f"{(e.get('involvedObject') or {}).get('kind', '')}/"
                        f"{(e.get('involvedObject') or {}).get('name', '')}"
                        for e in evts
                    }
                )
            )[:200],
            description="The cluster reported warning events for this workload.",
            evidence=[f"{sum(_event_count(e) for e in evts)} occurrences", evts[0].get("message", "")[:200]],
            recommendation="Investigate the event message; it usually names the failing dependency.",
        )
        for reason, evts in grouped.items()
    ]


def _hpa_metrics(hpa: dict) -> list[tuple[str, float | None, float | None]]:
    """Return (resource, current%, target%) for resource metrics in an autoscaling/v2 HPA."""
    targets = {
        m["resource"]["name"]: m["resource"].get("target", {}).get("averageUtilization")
        for m in hpa.get("spec", {}).get("metrics", [])
        if m.get("type") == "Resource"
    }
    if "targetCPUUtilizationPercentage" in hpa.get("spec", {}):
        targets["cpu"] = hpa["spec"]["targetCPUUtilizationPercentage"]
    current = {
        m["resource"]["name"]: m["resource"].get("current", {}).get("averageUtilization")
        for m in hpa.get("status", {}).get("currentMetrics") or []
        if m.get("type") == "Resource"
    }
    if "currentCPUUtilizationPercentage" in hpa.get("status", {}):
        current["cpu"] = hpa["status"]["currentCPUUtilizationPercentage"]
    return [(k, current.get(k), v) for k, v in targets.items()]


@rule
def hpa_at_max(ctx: RuleContext) -> list[Finding]:
    hpa = ctx.snapshot.hpa
    if not hpa:
        return []
    spec, status = hpa.get("spec", {}), hpa.get("status", {})
    max_r, cur = spec.get("maxReplicas"), status.get("currentReplicas", 0)
    if not max_r or cur < max_r:
        return []
    over = [(k, c, t) for k, c, t in _hpa_metrics(hpa) if c is not None and t and c > t]
    return [
        Finding(
            rule_id="hpa_at_max",
            title="Autoscaler pinned at maxReplicas",
            severity=Severity.HIGH if over else Severity.MEDIUM,
            category="capacity",
            resource=f"hpa/{hpa['metadata']['name']}",
            description="The HPA wants more replicas but is capped, so additional load queues up in existing pods.",
            evidence=[f"currentReplicas={cur} maxReplicas={max_r}"]
            + [f"{k}: {c}% of request (target {t}%)" for k, c, t in over],
            recommendation="Raise maxReplicas (check quota/cluster capacity first) or make each pod more efficient.",
        )
    ]


@rule
def node_pressure(ctx: RuleContext) -> list[Finding]:
    t, out = ctx.thresholds, []
    util = {
        key: {s["labels"].get("instance"): s["value"] for s in ctx.instant(key)}
        for key in ("node_cpu_util", "node_memory_util")
    }
    for name, node in ctx.snapshot.nodes.items():
        conds = {c["type"]: c for c in node.get("status", {}).get("conditions", [])}
        evidence, sev = [], None
        if conds.get("Ready", {}).get("status") not in (None, "True"):
            evidence.append(f"Ready={conds['Ready']['status']}: {conds['Ready'].get('message', '')}")
            sev = Severity.CRITICAL
        for p in ("MemoryPressure", "DiskPressure", "PIDPressure"):
            if conds.get(p, {}).get("status") == "True":
                evidence.append(f"{p}=True")
                sev = sev or Severity.HIGH
        for key, label in (("node_cpu_util", "CPU"), ("node_memory_util", "memory")):
            v = util[key].get(name)
            if v is not None and v >= t.node_util_warn:
                evidence.append(f"node {label} utilisation {fmt_pct(v)}")
                sev = sev or Severity.MEDIUM
        if sev:
            pods = sorted({c.pod for c in ctx.containers if c.node == name})
            out.append(
                Finding(
                    rule_id="node_pressure",
                    title="Hosting node under pressure",
                    severity=sev,
                    category="node",
                    resource=f"node/{name}",
                    description="A node running this deployment's pods is saturated, causing noisy-neighbour "
                    "contention or evictions.",
                    evidence=evidence + [f"pods on node: {', '.join(pods)}"],
                    recommendation="Spread pods with topologySpreadConstraints/anti-affinity and add capacity.",
                )
            )
    return out


@rule
def quota_exhaustion(ctx: RuleContext) -> list[Finding]:
    out = []
    for q in ctx.snapshot.quotas:
        hard, used = q.get("status", {}).get("hard", {}), q.get("status", {}).get("used", {})
        for key, limit in hard.items():
            parse = parse_cpu if "cpu" in key else parse_memory
            h, u = parse(limit), parse(used.get(key, 0))
            if not h or u is None or u / h < ctx.thresholds.quota_warn:
                continue
            out.append(
                Finding(
                    rule_id="quota_exhaustion",
                    title=f"ResourceQuota '{key}' nearly exhausted",
                    severity=Severity.HIGH if u >= h else Severity.MEDIUM,
                    category="capacity",
                    resource=f"resourcequota/{q['metadata']['name']}",
                    description="New pods (scale-out, rollouts) will be rejected once the quota is hit.",
                    evidence=[f"{key}: used {used.get(key)} of {limit} ({fmt_pct(u / h)})"],
                    recommendation="Request a quota increase or reclaim over-provisioned requests.",
                )
            )
    return out


@rule
def load_imbalance(ctx: RuleContext) -> list[Finding]:
    by_container: dict[str, list[ContainerStats]] = defaultdict(list)
    for c in ctx.containers:
        if c.cpu_usage is not None and c.phase == "Running":
            by_container[c.container].append(c)
    out = []
    for name, items in by_container.items():
        if len(items) < 2:
            continue
        hi, lo = max(items, key=lambda c: c.cpu_usage), min(items, key=lambda c: c.cpu_usage)
        if hi.cpu_usage > 0.05 and hi.cpu_usage / max(lo.cpu_usage, 0.001) >= ctx.thresholds.imbalance_ratio:
            out.append(
                Finding(
                    rule_id="load_imbalance",
                    title="Uneven load across replicas",
                    severity=Severity.LOW,
                    category="cpu",
                    resource=f"container/{name}",
                    description="One replica is doing much more work than others (sticky sessions, hot "
                    "partition or uneven connection pooling).",
                    evidence=[f"{hi.pod}: {fmt_cpu(hi.cpu_usage)} vs {lo.pod}: {fmt_cpu(lo.cpu_usage)}"],
                    recommendation="Check session affinity on the Service/Route and client connection reuse.",
                )
            )
    return out


@rule
def high_latency(ctx: RuleContext) -> list[Finding]:
    samples = ctx.instant("http_p95_latency")
    if not samples:
        return []
    p95, warn = samples[0]["value"], ctx.thresholds.latency_p95_warn_s
    if p95 < warn:
        return []
    return [
        Finding(
            rule_id="high_latency",
            title="High p95 request latency",
            severity=Severity.HIGH if p95 >= 3 * warn else Severity.MEDIUM,
            category="latency",
            resource=f"deployment/{ctx.snapshot.deployment_name}",
            description="Users are experiencing slow responses.",
            evidence=[f"p95 latency {p95:.2f}s (threshold {warn:.1f}s)"],
            recommendation="Correlate with CPU throttling, GC and downstream timeouts in the logs.",
        )
    ]


@rule
def network_drops(ctx: RuleContext) -> list[Finding]:
    bad = [s for s in ctx.instant("net_drops") if s["value"] >= ctx.thresholds.net_drops_warn]
    return [
        Finding(
            rule_id="network_drops",
            title="Network packet drops",
            severity=Severity.MEDIUM,
            category="network",
            resource=f"pod/{s['labels'].get('pod')}",
            description="Packets are being dropped on the pod interface.",
            evidence=[f"{s['value']:.1f} dropped packets/s"],
            recommendation="Check NetworkPolicies, node NIC saturation and OVN/SDN health.",
        )
        for s in bad
    ]


LOG_RULES = {
    "out_of_memory": (Severity.HIGH, "memory", "Fix memory usage or raise the limit."),
    "db_pool": (
        Severity.HIGH,
        "dependency",
        "Pool exhausted: size the pool vs. DB max_connections and check for slow queries / leaked connections.",
    ),
    "timeout": (Severity.MEDIUM, "dependency", "Find the slow downstream; tune timeouts and add circuit breakers."),
    "connection": (
        Severity.MEDIUM,
        "dependency",
        "A dependency is unreachable; check its Service/endpoints and NetworkPolicies.",
    ),
    "dns": (Severity.MEDIUM, "network", "Check Service names and the cluster DNS operator."),
    "tls": (Severity.MEDIUM, "config", "Check certificate validity and trusted CA bundles."),
    "http_5xx": (Severity.MEDIUM, "latency", "Correlate 5xx spikes with restarts and downstream errors."),
    "slow": (Severity.MEDIUM, "latency", "Profile the slow operations reported in the logs."),
    "gc": (Severity.MEDIUM, "memory", "GC pressure: increase heap/limit or reduce allocation rate."),
    "exception": (Severity.LOW, "logs", "Review the most frequent exception templates."),
}


@rule
def log_patterns(ctx: RuleContext) -> list[Finding]:
    totals: dict[str, int] = defaultdict(int)
    where: dict[str, set[str]] = defaultdict(set)
    samples: dict[str, list[str]] = defaultdict(list)
    for li in ctx.log_insights:
        for cat, n in li.category_counts.items():
            totals[cat] += n
            where[cat].add(f"{li.pod}/{li.container}{' (previous)' if li.previous else ''}")
            samples[cat].extend(li.samples.get(cat, []))
    out = []
    for cat, (sev, category, rec) in LOG_RULES.items():
        n = totals.get(cat, 0)
        if n < 3 and cat != "out_of_memory" or n == 0:
            continue
        if sev == Severity.MEDIUM and n >= 50:
            sev = Severity.HIGH
        out.append(
            Finding(
                rule_id=f"logs_{cat}",
                title=f"Log pattern: {cat.replace('_', ' ')} ({n} lines)",
                severity=sev,
                category=category,
                resource=", ".join(sorted(where[cat]))[:200],
                description="Recurring error signature found in container logs.",
                evidence=list(dict.fromkeys(samples[cat]))[:3],
                recommendation=rec,
            )
        )
    return out


def run_rules(ctx: RuleContext, rules: list[Rule] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for fn in rules or RULES:
        findings.extend(fn(ctx))
    return sorted(findings, key=lambda f: (f.severity.rank, f.category, f.resource))


def health_score(findings: list[Finding]) -> int:
    """0-100 score that decays with the worst severity per rule plus a small penalty per repeat occurrence."""
    by_rule: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_rule[f.rule_id].append(f)
    penalty = 0
    for items in by_rule.values():
        weights = sorted((f.severity.weight for f in items), reverse=True)
        penalty += weights[0] + sum(min(w, 2) for w in weights[1:])
    return round(100 * math.exp(-penalty / 120))
