"""Step 4 - the official client: resolve the card, let the SDK pick the transport, send a protobuf Message.

New idea: clients bind to the CARD, not to a URL you hard-code. If the agent later adds gRPC or moves,
the card changes and the client follows."""

import asyncio
import uuid

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_artifact_text
from a2a.types import Message, Part, Role, SendMessageRequest
from common import Running, title
from step03_sdk_server import PORT, app


async def main(url: str) -> None:
    async with httpx.AsyncClient() as http:
        card = await A2ACardResolver(http, url).get_agent_card()
    title(f"resolved card: {card.name} skills={[s.id for s in card.skills]}")
    client = await create_client(card, client_config=ClientConfig(streaming=False))
    msg = Message(role=Role.ROLE_USER, parts=[Part(text="payments 5xx burst")], message_id=str(uuid.uuid4()))
    async for chunk in client.send_message(SendMessageRequest(message=msg)):
        if chunk.HasField("task"):
            t = chunk.task
            print(TaskStateName(t.status.state), "->", get_artifact_text(t.artifacts[0]))


def TaskStateName(v):  # noqa: N802
    from a2a.types import TaskState

    return TaskState.Name(v)


with Running(app, PORT) as srv:
    asyncio.run(main(srv.url))
