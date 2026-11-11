"""Read-only view of the lab's chaos switches. In the lab, active chaos *is* the 'recent change'; in production the
same tool slot would read deploys, feature flags and config changes."""

from __future__ import annotations

from typing import Any

from .http import BackendClient


class ChangeBackend:
    def __init__(self, client: BackendClient) -> None:
        self.client = client

    def recent_changes(self) -> dict[str, Any]:
        data = self.client.get_json("/api/chaos", cache=False)
        active = {}
        for svc, cfg in data.get("services", {}).items():
            on = {k: v for k, v in cfg.items() if v not in (0, 0.0, False, [], None)}
            if on:
                active[svc] = on
        return {"source": "shopsphere chaos API", "active_faults": active, "any_active": bool(active)}
