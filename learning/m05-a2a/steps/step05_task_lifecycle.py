"""Step 5 - task states are the contract: SUBMITTED -> WORKING -> COMPLETED | FAILED | REJECTED | INPUT_REQUIRED.

New idea: a remote agent can say "no" (REJECTED), crash (the SDK turns the exception into an error) or
pause for more input (INPUT_REQUIRED) - and the caller must branch on the state, never assume success.
Note: on a blocking SendMessage an uncaught exception surfaces as a JSON-RPC error (-32603), so handle both."""

from a2a.helpers import new_text_part
from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_jsonrpc_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import Task, TaskState, TaskStatus
from common import Running, rpc, title, user_text
from starlette.applications import Starlette
from step03_sdk_server import card


class Moody(AgentExecutor):
    async def execute(self, context, event_queue):
        tid, cid, text = context.task_id, context.context_id, context.get_user_input()
        await event_queue.enqueue_event(
            Task(id=tid, context_id=cid, status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED))
        )
        up = TaskUpdater(event_queue=event_queue, task_id=tid, context_id=cid)
        if "rm -rf" in text:
            return await up.reject(up.new_agent_message(parts=[new_text_part("not an SRE question")]))
        if "boom" in text:
            raise RuntimeError("backend exploded")
        if "which service" not in text and "service=" not in text:
            return await up.requires_input(up.new_agent_message(parts=[new_text_part("which service?")]))
        await up.start_work()
        await up.add_artifact(parts=[new_text_part("ok: " + text)], name="answer")
        await up.complete()

    async def cancel(self, context, event_queue):
        pass


h = DefaultRequestHandler(agent_executor=Moody(), task_store=InMemoryTaskStore(), agent_card=card)
app = Starlette(routes=create_jsonrpc_routes(request_handler=h, rpc_url="/a2a/jsonrpc"))
with Running(app, 9305) as srv:
    for q in ["latency high service=payments", "latency high", "rm -rf /", "boom"]:
        out = rpc(srv.url + "/a2a/jsonrpc", "SendMessage", user_text(q))
        res = out.get("result", {}).get("task") or out.get("error")
        state = res.get("status", {}).get("state") if "status" in res else f"error {res}"
        title(f"{q!r} -> {state}")
