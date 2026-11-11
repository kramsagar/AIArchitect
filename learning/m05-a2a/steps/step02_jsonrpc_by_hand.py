"""Step 2 - the wire protocol by hand: JSON-RPC 2.0 `SendMessage` -> a Task.

New idea: request = Message (role + parts), response = Task (id, contextId, status.state, artifacts).
We write a 25-line server WITHOUT the SDK so nothing is magic. Step 3 replaces it with the SDK."""

import uuid

from common import Running, rpc, title, user_text
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route


async def jsonrpc(request):
    req = await request.json()
    if req.get("method") != "SendMessage":
        return JSONResponse({"jsonrpc": "2.0", "id": req.get("id"), "error": {"code": -32601, "message": "no method"}})
    msg = req["params"]["message"]
    text = " ".join(p.get("text", "") for p in msg["parts"])
    task = {
        "id": str(uuid.uuid4()),
        "contextId": msg.get("contextId") or str(uuid.uuid4()),
        "status": {"state": "TASK_STATE_COMPLETED"},
        "artifacts": [{"artifactId": "a1", "name": "answer", "parts": [{"text": f"triage says: sev2 for '{text}'"}]}],
    }
    return JSONResponse({"jsonrpc": "2.0", "id": req["id"], "result": {"task": task}})


app = Starlette(routes=[Route("/a2a/jsonrpc", jsonrpc, methods=["POST"])])
with Running(app, 9302) as srv:
    title("SendMessage")
    out = rpc(srv.url + "/a2a/jsonrpc", "SendMessage", user_text("checkout p99 high"))
    task = out["result"]["task"]
    print(task["status"]["state"], "->", task["artifacts"][0]["parts"][0]["text"])
    title("unknown method -> JSON-RPC error object, not an HTTP 500")
    print(rpc(srv.url + "/a2a/jsonrpc", "Nope", {}))
