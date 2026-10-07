"""User acceptance tests: the full connect -> select deployment -> analyze journey in demo mode."""

import json
import re

import pytest
from playwright.sync_api import Page, expect

TIMEOUT = 60_000


def _connect(page: Page, app_url: str) -> None:
    page.goto(app_url)
    expect(page.get_by_label("Cluster API URL")).to_have_value("https://api.demo.ocp.local:6443", timeout=TIMEOUT)
    page.get_by_role("button", name="Connect").click()
    expect(page.get_by_text("Connected as demo-user")).to_be_visible(timeout=TIMEOUT)


def _analyze(page: Page, deployment: str) -> dict[str, str]:
    page.locator('[data-testid="stSelectbox"]').filter(has_text="Deployment").click()
    page.get_by_role("option", name=re.compile(rf"^{deployment} ")).click()
    page.get_by_role("button", name="Analyze bottlenecks").click()
    expect(page.get_by_role("tab", name="Findings")).to_be_visible(timeout=TIMEOUT)
    expect(page.locator('[data-testid="stMetric"]').first).to_contain_text("Health score", timeout=TIMEOUT)
    metrics = {}
    for m in page.locator('[data-testid="stMetric"]').all():
        label = m.locator('[data-testid="stMetricLabel"]').inner_text().strip()
        metrics[label] = m.locator('[data-testid="stMetricValue"]').inner_text().strip()
    return metrics


def _expect_finding(page: Page, pattern: str) -> None:
    """A finding expander whose header matches ``pattern`` is visible on the Findings tab."""
    header = page.locator('[data-testid="stExpander"] summary').filter(has_text=re.compile(pattern, re.I))
    expect(header.first).to_be_visible(timeout=TIMEOUT)


def _no_exceptions(page: Page) -> None:
    expect(page.locator('[data-testid="stException"]')).to_have_count(0)


def test_connect_lists_demo_deployments(page: Page, app_url, shot):
    _connect(page, app_url)
    page.locator('[data-testid="stSelectbox"]').filter(has_text="Deployment").click()
    options = page.get_by_role("option").all_inner_texts()
    shot("deployments")
    assert [o.split()[0] for o in options] == ["checkout-service", "payment-gateway", "catalog-service"]
    _no_exceptions(page)


def test_checkout_service_full_report(page: Page, app_url, shot):
    _connect(page, app_url)
    metrics = _analyze(page, "checkout-service")
    shot("summary")
    assert metrics["Health score"] == "18/100"
    assert metrics["Critical"] == "1"
    assert int(metrics["High"]) >= 10
    assert [t.strip() for t in page.get_by_role("tab").all_inner_texts()] == [
        "Summary", "Findings", "Metrics", "Pods & events", "Logs", "Agent trace", "Export",
    ]  # fmt: skip
    expect(page.get_by_text("CPU capacity ceiling").first).to_be_visible()

    page.get_by_role("tab", name="Findings").click()
    for title in (
        "OOM killer",
        "Autoscaler pinned at maxReplicas",
        "CPU throttled by CFS quota",
        "Pod cannot be scheduled",
    ):
        _expect_finding(page, title)
    shot("findings")

    page.get_by_role("tab", name="Metrics").click()
    expect(page.locator('[data-testid="stPlotlyChart"]')).to_have_count(4, timeout=TIMEOUT)
    expect(page.get_by_text("pod limit").first).to_be_attached()
    shot("metrics")

    page.get_by_role("tab", name="Logs").click()
    expect(page.get_by_text(re.compile("db_pool|DB connection pool", re.I)).first).to_be_attached()
    _no_exceptions(page)


def test_export_downloads_reports(page: Page, app_url, shot, tmp_path):
    _connect(page, app_url)
    _analyze(page, "checkout-service")
    page.get_by_role("tab", name="Export").click()
    with page.expect_download() as md:
        page.get_by_role("button", name="Download Markdown report").click()
    md_path = tmp_path / md.value.suggested_filename
    md.value.save_as(md_path)
    assert md_path.name == "bottleneck-shop-checkout-service.md"
    assert "# Bottleneck report: shop/checkout-service" in md_path.read_text()

    with page.expect_download() as js:
        page.get_by_role("button", name="Download JSON report").click()
    js_path = tmp_path / js.value.suggested_filename
    js.value.save_as(js_path)
    data = json.loads(js_path.read_text())
    assert data["health_score"] == 18 and data["findings"]
    shot("export")


@pytest.mark.parametrize(
    ("deployment", "score", "expected"),
    [
        ("payment-gateway", "54/100", ["CrashLoopBackOff|restarting repeatedly", "DNS"]),
        ("catalog-service", "87/100", ["over-provisioned|well below request"]),
    ],
)
def test_other_scenarios(page: Page, app_url, shot, deployment, score, expected):
    _connect(page, app_url)
    metrics = _analyze(page, deployment)
    assert metrics["Health score"] == score
    page.get_by_role("tab", name="Findings").click()
    for pattern in expected:
        _expect_finding(page, pattern)
    shot("findings")
    _no_exceptions(page)


def test_live_mode_requires_api_url(page: Page, app_url, shot):
    page.goto(app_url)
    page.get_by_text("Demo mode (synthetic cluster)").click()
    expect(page.get_by_label("Cluster API URL")).to_have_value("", timeout=TIMEOUT)
    page.get_by_role("button", name="Connect").click()
    expect(page.get_by_text("Cluster API URL is required")).to_be_visible(timeout=TIMEOUT)
    shot("validation")
    _no_exceptions(page)
