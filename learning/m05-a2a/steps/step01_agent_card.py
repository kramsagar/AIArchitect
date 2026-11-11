"""Step 1 - the Agent Card: a machine-readable CV published at /.well-known/agent-card.json.

New idea: discovery. The card says who the agent is, which skills it has, which transport/URL to use,
input/output media types and capabilities. Clients read the card BEFORE they send anything."""

import json

import httpx
from a2a.server.routes import create_agent_card_routes
from common import Running, title
from google.protobuf.json_format import MessageToDict
from starlette.applications import Starlette

from m05_a2a.agents import AGENTS
from m05_a2a.server import build_card

card = build_card(AGENTS["rca-agent"], "http://127.0.0.1:9301", auth=False)
title("the card as a protobuf object (a2a-sdk 1.x types are protobuf)")
print(type(card).__name__, card.name, [s.id for s in card.skills])

app = Starlette(routes=create_agent_card_routes(agent_card=card))
with Running(app, 9301) as srv:
    title("GET /.well-known/agent-card.json (camelCase JSON on the wire)")
    wire = httpx.get(srv.url + "/.well-known/agent-card.json").json()
    print(json.dumps(wire, indent=1)[:900])
    assert wire == MessageToDict(card)
