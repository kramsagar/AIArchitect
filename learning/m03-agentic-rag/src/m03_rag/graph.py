"""GraphRAG-lite: some questions are about *relationships* ("what breaks if redis fails?", "who owns the thing
checkout calls?"). Similarity search cannot follow edges; a graph can. The graph is parsed from service-graph.md
so the docs stay the single source of truth."""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path

EDGE = re.compile(r"^- ([\w-]+) -> ([\w-]+) \(([^)]*)\)", re.M)
OWNER = re.compile(r"^- ([\w-]+): team ([\w-]+), on-call rotation `([\w-]+)`(?:, (.+))?$", re.M)


class ServiceGraph:
    def __init__(self, path: Path | None = None) -> None:
        text = (path or Path(__file__).resolve().parent / "corpus" / "service-graph.md").read_text("utf-8")
        self.edges = [(a, b, info) for a, b, info in EDGE.findall(text)]
        self.owners = {s: {"team": t, "oncall": o, "docs": (d or "").split(", ") if d else []}
                       for s, t, o, d in OWNER.findall(text)}  # fmt: skip
        self.nodes = sorted({n for a, b, _ in self.edges for n in (a, b)})

    def dependencies(self, service: str) -> list[dict]:
        return [{"service": b, "via": info} for a, b, info in self.edges if a == service]

    def dependents(self, service: str) -> list[str]:
        return [a for a, b, _ in self.edges if b == service]

    def blast_radius(self, service: str) -> list[str]:
        """Everything that transitively calls `service`: what is impacted if it fails (BFS upstream)."""
        seen, queue = set(), deque([service])
        while queue:
            for caller in self.dependents(queue.popleft()):
                if caller not in seen:
                    seen.add(caller)
                    queue.append(caller)
        return sorted(seen)

    def describe(self, service: str) -> dict:
        if service not in self.nodes:
            return {"error": f"unknown service {service!r}", "known": self.nodes}
        return {"service": service, "depends_on": self.dependencies(service), "called_by": self.dependents(service),
                "blast_radius": self.blast_radius(service), "owner": self.owners.get(service)}  # fmt: skip
