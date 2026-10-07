"""UAT fixtures: run the Streamlit app in demo mode and drive it with Playwright."""

import os
import pathlib
import re
import socket
import subprocess
import sys
import time

import pytest
import requests

pytest.importorskip("playwright")

PROJECT = pathlib.Path(__file__).resolve().parents[2]
SCREENSHOTS = PROJECT / "test-reports" / "uat" / "screenshots"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def app_url():
    port = _free_port()
    env = {**os.environ, "DEMO_MODE": "true"}
    for key in ("OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "OPENAI_BASE_URL"):
        env.pop(key, None)
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app/streamlit_app.py",
            "--server.port", str(port), "--server.address", "127.0.0.1",
            "--server.headless", "true", "--browser.gatherUsageStats", "false",
        ],
        cwd=PROJECT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )  # fmt: skip
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                if requests.get(f"{url}/_stcore/health", timeout=1).ok:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("Streamlit did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 1440, "height": 1000}, "accept_downloads": True}


@pytest.fixture
def shot(page, request):
    """Save a named full-page screenshot under test-reports/uat/screenshots/."""
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)

    def _shot(name: str) -> None:
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{request.node.name}-{name}").strip("_")
        page.screenshot(path=SCREENSHOTS / f"{stem}.png", full_page=True)

    return _shot
