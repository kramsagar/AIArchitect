import pathlib

import pytest

from ocp_analyzer.demo import DemoKube, DemoPrometheus

_SUITES = ("functional", "regression", "uat")


def pytest_collection_modifyitems(items):
    """Mark every test with its suite, taken from its directory under tests/."""
    for item in items:
        parts = pathlib.Path(str(item.fspath)).parts
        for suite in _SUITES:
            if suite in parts:
                item.add_marker(getattr(pytest.mark, suite))


@pytest.fixture
def kube():
    return DemoKube()


@pytest.fixture
def prom():
    return DemoPrometheus()
