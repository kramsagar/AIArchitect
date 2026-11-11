"""What the crew can see and do. Reads go through Module 2's backends (fixture or live lab) and Module 3's hybrid
retriever; the single write is `reset_faults` (the lab's "rollback": clear the chaos config of one service).

Fixture mode keeps a tiny mutable "world": resetting the faulty service flips the scenario to `healthy`, so the
verifier sees recovery exactly like it would against the real lab."""

from __future__ import annotations

from typing import Any

import httpx
from m02_obs.backends import Backends, build_backends
from m02_obs.config import ObsConfig

CHAOS_NAME = {"shopsphere-shop": "shop", "payments-service": "payments"}  # Jaeger/Prometheus name -> chaos API name
OTEL_NAME = {v: k for k, v in CHAOS_NAME.items()}


class Toolbox:
    def __init__(self, backend: str = "fixture", scenario: str = "checkout-latency", config: ObsConfig | None = None):
        self.config = config or ObsConfig.from_env(backend=backend, scenario=scenario if backend == "fixture" else None)
        self.mode = self.config.backend
        self.scenario = self.config.scenario
        self._live: Backends | None = None
        self._retriever = None
        self.writes: list[dict] = []  # audit of every side effect performed through this toolbox

    @property
    def be(self) -> Backends:
        if self.mode == "fixture":  # rebuilt on access so a remediation is visible immediately
            return build_backends(self.config.model_copy(update={"scenario": self.scenario}))
        if self._live is None:
            self._live = build_backends(self.config)
        return self._live

    # ---------------------------------------------------------------- reads
    def slo(self) -> dict[str, Any]:
        return self.be.metrics.slo_status()

    def alerts(self) -> dict[str, Any]:
        return self.be.metrics.alerts()

    def traces(self, service: str, *, errors_only: bool = False, min_duration_ms: int | None = None, limit: int = 3):
        return self.be.traces.search(service, None, errors_only, min_duration_ms, 15, limit)

    def logs(self, spl: str, limit: int = 10) -> dict[str, Any]:
        return self.be.logs.search(spl, 15, limit)

    def changes(self) -> dict[str, Any]:
        return self.be.changes.recent_changes()

    def runbooks(self, query: str, k: int = 3) -> list[dict[str, str]]:
        from m03_rag.hybrid import HybridRetriever
        from m03_rag.rerank import lexical_rerank

        if self._retriever is None:
            self._retriever = HybridRetriever()
        hits = lexical_rerank(query, self._retriever.search(query, k=15), k=k)
        return [{"id": h.chunk.id, "text": h.chunk.text[:400]} for h in hits]

    # ---------------------------------------------------------------- the one write
    def reset_faults(self, service: str, idempotency_key: str) -> dict[str, Any]:
        if service not in OTEL_NAME:
            raise ValueError(f"unknown service {service!r}; allowed: {sorted(OTEL_NAME)}")
        if any(w["key"] == idempotency_key for w in self.writes):
            return {"service": service, "result": "already done", "key": idempotency_key}
        if self.mode == "fixture":
            if service in self.changes()["active_faults"]:
                self.scenario = "healthy"
            result = "fixture world reset"
        else:
            r = httpx.put(f"{self.config.shop_url}/api/chaos/{service}", json={}, timeout=self.config.timeout_s)
            r.raise_for_status()
            result = f"PUT /api/chaos/{service} -> {r.status_code}"
        self.writes.append({"key": idempotency_key, "service": service, "result": result})
        return {"service": service, "result": result, "key": idempotency_key}
