import os
import runpy
from pathlib import Path

import pytest

STEPS = sorted((Path(__file__).resolve().parents[1] / "steps").glob("step*.py"))


@pytest.mark.parametrize("path", STEPS, ids=lambda p: p.stem)
def test_step_runs_offline(path, tmp_path, monkeypatch):
    monkeypatch.setenv("M04_OFFLINE", "1")
    monkeypatch.setenv("OBS_BACKEND", "fixture")
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(path), run_name="__main__")
    assert os.getcwd() == str(tmp_path)
