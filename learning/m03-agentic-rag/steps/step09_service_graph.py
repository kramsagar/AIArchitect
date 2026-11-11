"""Step 9 - GraphRAG-lite: parse service-graph.md into edges, then answer relationship questions by traversal.
"What breaks if redis fails?" = everything that transitively calls redis (BFS upstream).

Run:  python steps/step09_service_graph.py redis
"""

import re
import sys
from collections import deque

from common import BY_ID

EDGES = re.findall(r"^- ([\w-]+) -> ([\w-]+) \(([^)]*)\)", BY_ID["service-graph#dependencies"].text, re.M)


def callers(service: str) -> list[str]:
    return [a for a, b, _ in EDGES if b == service]


def blast_radius(service: str) -> list[str]:
    seen, queue = set(), deque([service])
    while queue:
        for c in callers(queue.popleft()):
            if c not in seen:
                seen.add(c)
                queue.append(c)
    return sorted(seen)


if __name__ == "__main__":
    s = sys.argv[1] if len(sys.argv) > 1 else "redis"
    print(f"edges: {len(EDGES)}\n{s} calls   : {[(b, i) for a, b, i in EDGES if a == s]}")
    print(f"called by : {callers(s)}\nblast radius if {s} fails: {blast_radius(s)}")
