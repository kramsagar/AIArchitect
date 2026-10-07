import pytest

from ocp_analyzer.demo import DemoKube, DemoPrometheus


@pytest.fixture
def kube():
    return DemoKube()


@pytest.fixture
def prom():
    return DemoPrometheus()
