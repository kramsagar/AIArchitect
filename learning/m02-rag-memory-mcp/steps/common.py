"""Shared by every Module 2 step: .env, Claude client, lab URLs, and live-vs-offline switching.

If the Docker lab is running, steps use LIVE Prometheus / Jaeger / Splunk / ShopSphere.
If not (or OBS_BACKEND=fixture), they use the offline fixture of a checkout-latency incident from m02_obs.
"""

import os
from pathlib import Path

import anthropic
import httpx

from m02_obs.backends.fixtures import FixtureBackends


def load_env() -> None:
    for path in (Path.cwd() / ".env", Path(__file__).resolve().parent.parent / ".env"):
        if path.is_file():
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                key, sep, value = line.partition("=")
                if sep and not key.strip().startswith("#"):
                    os.environ.setdefault(key.strip(), value.split(" #")[0].strip())
            return


load_env()
MODEL = os.getenv("AGENT_MODEL", "claude-haiku-5-5")
PROMETHEUS = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
JAEGER = os.getenv("JAEGER_URL", "http://localhost:16686")
SPLUNK = os.getenv("SPLUNK_URL", "https://localhost:8090")
SPLUNK_AUTH = (os.getenv("SPLUNK_USERNAME", "admin"), os.getenv("SPLUNK_PASSWORD", "ShopSphere#Lab1"))
SHOP = os.getenv("SHOP_URL", "http://localhost:8080")
REPO = Path(__file__).resolve().parents[3]
CORPUS_DIRS = [REPO / "lab" / "docs", Path(__file__).resolve().parent.parent / "src" / "m02_obs" / "corpus"]


def _lab_up() -> bool:
    if os.getenv("OBS_BACKEND", "live") == "fixture":
        return False
    try:
        return httpx.get(f"{PROMETHEUS}/-/ready", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


LIVE = _lab_up()
FIX = FixtureBackends(os.getenv("OBS_FIXTURE_SCENARIO", "checkout-latency"))


def mode() -> str:
    return "LIVE lab" if LIVE else f"OFFLINE fixture ({FIX.scenario})"


def client() -> anthropic.Anthropic:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set: put it in .env or run  $env:ANTHROPIC_API_KEY = 'sk-ant-...'")
    return anthropic.Anthropic(max_retries=2, timeout=60)


def text_of(resp) -> str:
    return "".join(b.text for b in resp.content if b.type == "text")
