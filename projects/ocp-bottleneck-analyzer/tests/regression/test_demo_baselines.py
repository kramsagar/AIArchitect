"""Golden-output regression tests: demo scenario results must not drift without updating baselines.json.

Regenerate intentionally with ``python scripts/update_baselines.py``.
"""

import json
import pathlib

import pytest

from ocp_analyzer.analyzer import run_analysis
from ocp_analyzer.report import to_markdown

BASELINES = json.loads((pathlib.Path(__file__).parent / "baselines.json").read_text())


@pytest.mark.parametrize("deployment", sorted(BASELINES))
def test_demo_scenario_matches_baseline(kube, prom, deployment):
    expected = BASELINES[deployment]
    report = run_analysis(kube, prom, "shop", deployment)
    assert sorted({f.rule_id for f in report.findings}) == expected["rule_ids"]
    assert report.health_score == expected["health_score"]
    counts = {s: sum(1 for f in report.findings if f.severity.value == s) for s in expected["severity_counts"]}
    assert counts == expected["severity_counts"]


@pytest.mark.parametrize("deployment", sorted(BASELINES))
def test_report_export_is_complete(kube, prom, deployment):
    report = run_analysis(kube, prom, "shop", deployment)
    md = to_markdown(report)
    assert f"# Bottleneck report: shop/{deployment}" in md
    assert all(f.title in md for f in report.findings)
    data = json.loads(report.model_dump_json())
    assert data["health_score"] == report.health_score
    assert len(data["findings"]) == len(report.findings)
