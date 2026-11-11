"""Start A2A agents as uvicorn servers. `serve_all` runs every agent in one process (threads) for dev/tests;
in production each agent is its own deployment (M9) and they only meet over HTTP."""

from __future__ import annotations

import threading
import time

import httpx
import uvicorn
from m04_crew.crew import Crew
from m04_crew.llm import build_llm
from m04_crew.tools import Toolbox

from .agents import AGENTS
from .server import build_app


def make_crew(backend: str, scenario: str, provider: str) -> Crew:
    return Crew(Toolbox(backend, scenario), build_llm(provider))


def serve_one(name: str, backend="fixture", scenario="checkout-latency", provider="mock", host="127.0.0.1", token=None):
    spec = AGENTS[name]
    app = build_app(spec, make_crew(backend, scenario, provider), f"http://{host}:{spec.port}", token=token)
    return uvicorn.Server(uvicorn.Config(app, host=host, port=spec.port, log_level="warning"))


def serve_all(backend="fixture", scenario="checkout-latency", provider="mock", host="127.0.0.1", token=None):
    servers = [serve_one(n, backend, scenario, provider, host, token) for n in AGENTS]
    for s in servers:
        threading.Thread(target=s.run, daemon=True).start()
    for spec in AGENTS.values():
        for _ in range(100):
            try:
                httpx.get(f"http://{host}:{spec.port}/.well-known/agent-card.json", timeout=0.5)
                break
            except httpx.TransportError:
                time.sleep(0.05)
    return servers


def stop_all(servers) -> None:
    for s in servers:
        s.should_exit = True
    time.sleep(0.3)
