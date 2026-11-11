"""Step 0 - an agent is just a function... until another team needs to call it.

M4's triage ran in-process: crew.triage(state). Here we put the SAME function behind HTTP with plain Starlette.
New idea: a network boundary. Now the caller needs a URL, a payload format, timeouts and error handling -
and every team would invent their own. A2A is the agreed format for exactly this."""

import httpx
from common import Running, title
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from m05_a2a.launcher import make_crew

crew = make_crew("fixture", "checkout-latency", "mock")

title("in-process (M4)")
print(crew.triage({})["severity"], crew.triage({})["focus_service"])


async def triage(request):
    return JSONResponse(crew.triage(await request.json()))


app = Starlette(routes=[Route("/triage", triage, methods=["POST"])])
with Running(app, 9300) as srv:
    title("over HTTP (home-grown API)")
    out = httpx.post(srv.url + "/triage", json={}, timeout=5).json()
    print(out["severity"], out["focus_service"])
    print("Problem: how would another team DISCOVER this endpoint, its input format, or its auth? -> step 1")
