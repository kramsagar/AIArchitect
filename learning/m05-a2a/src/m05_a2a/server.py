"""Serve one M4 specialist as an A2A agent with the official a2a-sdk (JSON-RPC binding, protocol 1.0).

    GET  /.well-known/agent-card.json   discovery: who am I, which skills, where, how to auth
    POST /a2a/jsonrpc  SendMessage       a DataPart {"skill", "state", "thread_id"} -> Task with a data artifact

Auth: if M05_TOKEN is set, every A2A call needs `Authorization: Bearer <token>` (the card advertises it).
Tracing: the caller's `traceparent` header is echoed into the artifact so a hop can be correlated (M7 adds OTel)."""

from __future__ import annotations

import asyncio
import contextvars
import os
from typing import Any

from a2a.helpers import get_data_parts, new_data_part, new_text_part
from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentProvider,
    AgentSkill,
    Task,
    TaskState,
    TaskStatus,
)
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .agents import AgentSpec
from .client import restore_ints

TRACEPARENT: contextvars.ContextVar[str] = contextvars.ContextVar("traceparent", default="")


def build_card(spec: AgentSpec, base_url: str, auth: bool) -> AgentCard:
    return AgentCard(
        name=spec.name,
        description=spec.description + (" Requires Bearer token." if auth else ""),
        provider=AgentProvider(organization="ShopSphere SRE", url="https://github.com/kramsagar/AIArchitect"),
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["application/json"],
        default_output_modes=["application/json", "text/plain"],
        skills=[
            AgentSkill(
                id=s,
                name=s,
                description=f"M4 crew step '{s}': incident state in, partial state update out.",
                tags=["sre", "incident", "write" if spec.writes else "read-only"],
                input_modes=["application/json"],
                output_modes=["application/json"],
            )
            for s in spec.skills
        ],
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", protocol_version="1.0", url=f"{base_url}/a2a/jsonrpc")
        ],
    )


class SpecialistExecutor(AgentExecutor):
    """Bridges A2A to an M4 `Crew` method. The crew is stateless between calls: all state travels in the message."""

    def __init__(self, crew, skills: tuple[str, ...]) -> None:
        self.crew, self.skills = crew, skills

    async def execute(self, context, event_queue) -> None:
        tid, cid = context.task_id, context.context_id
        await event_queue.enqueue_event(
            Task(
                id=tid,
                context_id=cid,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
                history=[context.message],
            )
        )
        up = TaskUpdater(event_queue=event_queue, task_id=tid, context_id=cid)
        data = restore_ints((get_data_parts(context.message.parts) or [{}])[0])  # both directions lose ints
        skill = data.get("skill")
        if skill not in self.skills:
            await up.reject(up.new_agent_message(parts=[new_text_part(f"unknown skill {skill!r}; have {self.skills}")]))
            return
        await up.start_work()
        fn = getattr(self.crew, skill)
        state: dict[str, Any] = data.get("state") or {}
        args = (state, {"configurable": {"thread_id": data.get("thread_id", cid)}}) if skill == "executor" else (state,)
        update = await asyncio.to_thread(fn, *args)
        meta = {"agent": skill, "traceparent": TRACEPARENT.get()}
        await up.add_artifact(parts=[new_data_part({"update": update, "meta": meta})], name="update", last_chunk=True)
        await up.complete()

    async def cancel(self, context, event_queue) -> None:
        await TaskUpdater(event_queue=event_queue, task_id=context.task_id, context_id=context.context_id).cancel()


class AuthAndTrace(BaseHTTPMiddleware):
    def __init__(self, app, token: str | None) -> None:
        super().__init__(app)
        self.token = token

    async def dispatch(self, request, call_next):
        guarded = self.token and request.url.path.startswith("/a2a/")
        if guarded and request.headers.get("authorization") != f"Bearer {self.token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        TRACEPARENT.set(request.headers.get("traceparent", ""))
        return await call_next(request)


def build_app(spec: AgentSpec, crew, base_url: str, token: str | None = None) -> Starlette:
    token = token if token is not None else os.getenv("M05_TOKEN")
    card = build_card(spec, base_url, auth=bool(token))
    handler = DefaultRequestHandler(
        agent_executor=SpecialistExecutor(crew, spec.skills), task_store=InMemoryTaskStore(), agent_card=card
    )
    app = Starlette(
        routes=[
            *create_agent_card_routes(agent_card=card),
            *create_jsonrpc_routes(request_handler=handler, rpc_url="/a2a/jsonrpc"),
        ]
    )
    app.add_middleware(AuthAndTrace, token=token)
    return app
