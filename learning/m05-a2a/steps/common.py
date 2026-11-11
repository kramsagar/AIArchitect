"""Shared helpers for the M5 steps: start/stop a Starlette app on a port in a background thread."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("M05_TOKEN", "")


class Running:
    def __init__(self, app, port: int) -> None:
        self.port, self.url = port, f"http://127.0.0.1:{port}"
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=self.server.run, daemon=True).start()
        for _ in range(100):
            try:
                httpx.get(self.url + "/", timeout=0.3)
                return
            except httpx.TransportError:
                time.sleep(0.05)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        time.sleep(0.2)


def rpc(url: str, method: str, params: dict, headers: dict | None = None) -> dict:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return httpx.post(url, json=body, headers={"A2A-Version": "1.0", **(headers or {})}, timeout=30).json()


def user_text(text: str) -> dict:
    return {"message": {"role": "ROLE_USER", "messageId": os.urandom(4).hex(), "parts": [{"text": text}]}}


def title(s: str) -> None:
    print(f"\n=== {s} ===")
