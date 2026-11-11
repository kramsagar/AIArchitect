"""Step 8 - discovery: read every card in a registry, build skill -> (agent, endpoint).

New idea: the orchestrator never hard-codes "rca lives on :9104". It asks "who offers skill rca?".
Production: the registry is a service catalog / k8s Service list / API gateway; here it's a list of URLs."""

from common import title

from m05_a2a.agents import registry_urls
from m05_a2a.client import A2AClient
from m05_a2a.launcher import serve_all, stop_all

servers = serve_all(token="")
try:
    client = A2AClient(registry_urls(), token="")
    title("skill index")
    for skill, (agent, url) in client.discover().items():
        print(f"  {skill:10} -> {agent:16} {url}")
    title("who may write to production? (from card tags)")
    print([n for n, c in client.cards.items() if any("write" in s["tags"] for s in c["skills"])])
finally:
    stop_all(servers)
