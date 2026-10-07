from ocp_analyzer.analyzer import run_analysis
from ocp_analyzer.collector import collect
from ocp_analyzer.report import to_markdown


def _ids(report):
    return {f.rule_id for f in report.findings}


def test_collect_snapshot(kube, prom):
    snap = collect(kube, prom, "shop", "checkout-service")
    assert len(snap.pods) == 3
    assert snap.hpa["metadata"]["name"] == "checkout-service"
    assert set(snap.nodes) == {"worker-1", "worker-2"}
    assert "checkout-service-7d9f8b6c5d-m4qzt/checkout#previous" in snap.logs
    assert snap.metrics_source == "prometheus"
    assert snap.series["cpu_usage"]
    assert all(e["involvedObject"]["name"].startswith("checkout-service") for e in snap.events)


def test_checkout_bottlenecks(kube, prom):
    report = run_analysis(kube, prom, "shop", "checkout-service")
    expected = {
        "oom_killed",
        "cpu_throttling",
        "hpa_at_max",
        "pending_pod",
        "probe_failures",
        "replicas_unavailable",
        "logs_db_pool",
        "logs_timeout",
        "high_latency",
        "node_pressure",
        "quota_exhaustion",
    }
    assert expected <= _ids(report)
    assert report.findings[0].severity.value == "critical"
    assert report.summary_source == "rules"
    assert "CPU capacity ceiling" in report.summary_markdown
    assert report.health_score < 50
    md = to_markdown(report)
    assert "# Bottleneck report: shop/checkout-service" in md


def test_payment_crashloop(kube, prom):
    report = run_analysis(kube, prom, "shop", "payment-gateway")
    assert {"crash_looping", "logs_dns", "single_replica", "replicas_unavailable"} <= _ids(report)
    assert "DNS failure" in report.summary_markdown


def test_catalog_is_healthier(kube, prom):
    report = run_analysis(kube, prom, "shop", "catalog-service")
    ids = _ids(report)
    assert "overprovisioned" in ids
    assert not ids & {"oom_killed", "cpu_throttling", "crash_looping", "pending_pod"}
    assert report.health_score > 70


def test_metrics_api_fallback(kube):
    kube.get_pod_metrics = lambda ns: [
        {
            "metadata": {"name": "catalog-service-6f7c9d5b4-a1b2c"},
            "containers": [{"name": "catalog", "usage": {"cpu": "50m", "memory": "100Mi"}}],
        }
    ]
    report = run_analysis(kube, None, "shop", "catalog-service")
    assert report.snapshot.metrics_source == "metrics-api"
    c = next(c for c in report.containers if c.pod == "catalog-service-6f7c9d5b4-a1b2c")
    assert c.cpu_usage == 0.05


def test_collection_is_best_effort(kube, prom):
    def boom(_name):
        raise RuntimeError("nodes is forbidden")

    kube.get_node = boom
    report = run_analysis(kube, prom, "shop", "checkout-service")
    assert any("nodes is forbidden" in w for w in report.snapshot.warnings)
    assert "oom_killed" in _ids(report)
