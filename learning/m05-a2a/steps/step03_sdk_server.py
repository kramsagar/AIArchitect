"""Step 3 - the same server with the official a2a-sdk: AgentExecutor + TaskUpdater + DefaultRequestHandler.

New idea: you write only `execute()`. The SDK gives you the JSON-RPC dispatcher, task store, task ids,
status transitions, history and spec-correct errors. Same client call as step 2 works unchanged."""

from a2a.helpers import new_text_part
from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks.inmemory_task_store import InMemoryTaskStore
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Task, TaskState, TaskStatus
from common import Running, rpc, title, user_text
from starlette.applications import Starlette

PORT = 9303


class TriageExecutor(AgentExecutor):
    async def execute(self, context, event_queue):
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
        await up.start_work()
        answer = f"triage says: sev2 for '{context.get_user_input()}'"
        await up.add_artifact(parts=[new_text_part(answer)], name="answer", last_chunk=True)
        await up.complete()

    async def cancel(self, context, event_queue):
        pass


card = AgentCard(
    name="toy-triage",
    description="step 3",
    version="1",
    capabilities=AgentCapabilities(streaming=False),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[AgentSkill(id="triage", name="triage", description="score an alert", tags=["sre"])],
    supported_interfaces=[
        AgentInterface(protocol_binding="JSONRPC", protocol_version="1.0", url=f"http://127.0.0.1:{PORT}/a2a/jsonrpc")
    ],
)
handler = DefaultRequestHandler(agent_executor=TriageExecutor(), task_store=InMemoryTaskStore(), agent_card=card)
app = Starlette(
    routes=[
        *create_agent_card_routes(agent_card=card),
        *create_jsonrpc_routes(request_handler=handler, rpc_url="/a2a/jsonrpc"),
    ]
)

if __name__ == "__main__":
    with Running(app, PORT) as srv:
        title("SendMessage via the SDK server")
        task = rpc(srv.url + "/a2a/jsonrpc", "SendMessage", user_text("checkout p99 high"))["result"]["task"]
        print(task["status"]["state"], "->", task["artifacts"][0]["parts"][0]["text"])
        title("GetTask: the task store remembers it (ask again later by id)")
        got = rpc(srv.url + "/a2a/jsonrpc", "GetTask", {"id": task["id"]})["result"]
        print(got["id"] == task["id"], got["status"]["state"], "history:", len(got.get("history", [])))
