import pytest

from ocp_analyzer.utils import fmt_bytes, fmt_cpu, label_selector, parse_cpu, parse_memory


@pytest.mark.parametrize(
    ("value", "expected"),
    [("500m", 0.5), ("2", 2.0), ("0.25", 0.25), ("1500000n", 0.0015), (None, None), ("", None), ("bogus", None)],
)
def test_parse_cpu(value, expected):
    assert parse_cpu(value) == pytest.approx(expected) if expected is not None else parse_cpu(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [("512Mi", 512 * 2**20), ("1Gi", 2**30), ("1G", 1e9), ("128974848", 128974848), ("1e3", 1000), ("64Ki", 65536)],
)
def test_parse_memory(value, expected):
    assert parse_memory(value) == pytest.approx(expected)


def test_label_selector():
    sel = {
        "matchLabels": {"app": "web", "tier": "fe"},
        "matchExpressions": [
            {"key": "env", "operator": "In", "values": ["prod", "stage"]},
            {"key": "canary", "operator": "DoesNotExist"},
        ],
    }
    assert label_selector(sel) == "app=web,tier=fe,env in (prod,stage),!canary"
    assert label_selector(None) == ""


def test_formatters():
    assert fmt_bytes(512 * 2**20) == "512.0Mi"
    assert fmt_cpu(0.25) == "250m"
    assert fmt_bytes(None) == "-"
