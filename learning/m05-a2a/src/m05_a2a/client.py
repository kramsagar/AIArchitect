"""A thin A2A client over plain HTTP + JSON-RPC (so you can see the wire format), plus discovery by skill.

Discovery = fetch every card in a registry, index skill id -> JSON-RPC endpoint. Calls carry a W3C `traceparent`
and an optional bearer token, use timeouts and retries (M1 resilience), and fail loudly on non-completed tasks."""

from __future__ import annotations

import json
import os
import secrets
import time
from typing import Any

import httpx
from m01_agent.resilience import RetryPolicy, retry_call

RETRY = RetryPolicy(max_retries=2, base_delay_s=0.2, retry_on=(httpx.TransportError, httpx.HTTPStatusError))

A2A_HEADERS = {"A2A-Version": "1.0"}


def restore_ints(x):
    """A2A DataParts are protobuf `Value`s: every number is a double, so 0 comes back as 0.0.
    Narrow whole floats back to int, or idempotency keys like `...:0` silently become `...:0.0`."""
    if isinstance(x, float) and x.is_integer():
        return int(x)
    if isinstance(x, list):
        return [restore_ints(v) for v in x]
    if isinstance(x, dict):
        return {k: restore_ints(v) for k, v in x.items()}
    return x


class A2AError(RuntimeError):
    pass


def new_traceparent(trace_id: str | None = None) -> str:
    return f"00-{trace_id or secrets.token_hex(16)}-{secrets.token_hex(8)}-01"


class A2AClient:
    def __init__(self, registry: list[str], token: str | None = None, timeout_s: float = 30.0) -> None:
        self.registry, self.timeout_s = registry, timeout_s
        self.token = token if token is not None else os.getenv("M05_TOKEN")
        self.cards: dict[str, dict] = {}
        self.skills: dict[str, tuple[str, str]] = {}  # skill -> (agent name, endpoint)
        self.trace_id = secrets.token_hex(16)  # one trace per incident
        self.hops: list[dict] = []

    def _headers(self) -> dict[str, str]:
        h = {**A2A_HEADERS, "traceparent": new_traceparent(self.trace_id)}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def discover(self) -> dict[str, tuple[str, str]]:
        for base in self.registry:
            card = httpx.get(f"{base}/.well-known/agent-card.json", timeout=5).json()
            self.cards[card["name"]] = card
            url = next(i["url"] for i in card["supportedInterfaces"] if i["protocolBinding"] == "JSONRPC")
            for s in card["skills"]:
                if s["id"] in self.skills and self.skills[s["id"]][0] != card["name"]:
                    raise A2AError(f"skill {s['id']} offered by two agents")
                self.skills[s["id"]] = (card["name"], url)
        return self.skills

    def call(self, skill: str, state: dict[str, Any], thread_id: str = "") -> dict[str, Any]:
        if not self.skills:
            self.discover()
        if skill not in self.skills:
            raise A2AError(f"no agent offers skill {skill!r}")
        agent, url = self.skills[skill]
        body = {
            "jsonrpc": "2.0",
            "id": secrets.token_hex(4),
            "method": "SendMessage",
            "params": {
                "message": {
                    "role": "ROLE_USER",
                    "messageId": secrets.token_hex(8),
                    "parts": [{"data": {"skill": skill, "state": state, "thread_id": thread_id}}],
                }
            },
        }
        t0 = time.perf_counter()

        def post():
            payload = json.loads(json.dumps(body, default=str))
            r = httpx.post(url, json=payload, headers=self._headers(), timeout=self.timeout_s)
            if r.status_code in (502, 503, 504):
                r.raise_for_status()
            return r

        r, _attempts = retry_call(post, RETRY)
        if r.status_code == 401:
            raise A2AError(f"{agent}: unauthorized")
        data = r.json()
        if "error" in data:
            raise A2AError(f"{agent}: {data['error']}")
        task = data["result"]["task"]
        state_name = task["status"]["state"]
        ms = round(1000 * (time.perf_counter() - t0), 1)
        self.hops.append({"agent": agent, "skill": skill, "state": state_name, "ms": ms})
        if state_name != "TASK_STATE_COMPLETED":
            raise A2AError(f"{agent}/{skill}: task {state_name}")
        art = next(a for a in task.get("artifacts", []) if a.get("name") == "update")
        return restore_ints(art["parts"][0]["data"]["update"])
