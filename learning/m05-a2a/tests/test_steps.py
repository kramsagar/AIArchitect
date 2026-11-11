import os
import subprocess
import sys
from pathlib import Path

import pytest

STEPS = sorted((Path(__file__).resolve().parents[1] / "steps").glob("step*.py"))


@pytest.mark.parametrize("step", STEPS, ids=lambda p: p.stem)
def test_step_runs_offline(step):
    env = {**os.environ, "M05_TOKEN": ""}
    r = subprocess.run(
        [sys.executable, str(step)], capture_output=True, text=True, timeout=120, env=env, cwd=step.parent
    )
    assert r.returncode == 0, r.stderr[-2000:]
