# M5 step-by-step: from "a function behind HTTP" to a 7-agent A2A incident crew

Same pattern as M1-M4. For every step: **run it → see what's new → build it yourself → check yourself**.
Everything runs offline (fixture telemetry + mock LLM). From `learning\m05-a2a` with the venv active:

```powershell
python steps\step00_agent_over_http.py
git diff --no-index steps\step02_jsonrpc_by_hand.py steps\step03_sdk_server.py   # what's new between two steps
```

Build your own in `steps\my_a2a.py`, one layer per step.

| Step | Run | New idea | Build it yourself | Check yourself |
|---|---|---|---|---|
| 0 | `step00_agent_over_http.py` | network boundary: M4 `crew.triage` behind plain HTTP | serve one Crew method with Starlette on :9400 | What does the caller now need that an in-process call did not? |
| 1 | `step01_agent_card.py` | **Agent Card** at `/.well-known/agent-card.json` | build a card for your agent with 1 skill; GET it | Why is the card public while skills are authenticated? |
| 2 | `step02_jsonrpc_by_hand.py` | JSON-RPC `SendMessage`: Message in, Task out | hand-write the 25-line server; return an artifact | Why return a JSON-RPC error object instead of HTTP 500? |
| 3 | `step03_sdk_server.py` | official **a2a-sdk**: `AgentExecutor`, `TaskUpdater`, `DefaultRequestHandler`; `GetTask` | port your step-2 server to the SDK | What does the task store give you that step 2 lacked? |
| 4 | `step04_sdk_client.py` | official client: resolve card → `create_client` → `send_message` | call your server with the SDK client | Why bind to the card instead of a URL? |
| 5 | `step05_task_lifecycle.py` | task states: COMPLETED / INPUT_REQUIRED / REJECTED / error | make your agent reject a non-SRE question | Which states must the caller handle? |
| 6 | `step06_data_parts.py` | DataPart = JSON state; **protobuf ints → floats** trap | send a dict with an int and print what comes back | How would `0.0` break idempotency? |
| 7 | `step07_specialist_agent.py` | `m05_a2a.server.build_app`: skill id → Crew method; rejects other skills | expose `rca` as your own agent | Why are specialists stateless? |
| 8 | `step08_discovery.py` | registry → skill index; who may write (card tags) | add duplicate-skill detection | Where does the registry live in production? |
| 9 | `step09_auth_and_trace.py` | bearer token + W3C `traceparent` (one trace id per incident) | add a token check middleware | What should M8 replace the static token with? |
| 10 | `step10_resilience.py` | timeouts, retries, graceful degradation when an agent is down | wrap a call so the incident continues without logs | When must you NOT degrade silently? |
| 11 | `step11_full_a2a_crew.py` | the unchanged M4 graph with 11 remote skills on 7 agents; approval stays local | swap your in-process crew for `RemoteCrew` | Why keep checkpoints and approval in the orchestrator? |

## Map to production code

| You built | Production file |
|---|---|
| steps 1, 3, 7, 9 | `src/m05_a2a/server.py` (`build_card`, `SpecialistExecutor`, `AuthAndTrace`, `build_app`) |
| steps 2, 6, 8, 10 | `src/m05_a2a/client.py` (`A2AClient.discover/call`, `restore_ints`, retries) |
| step 7 | `src/m05_a2a/agents.py` (which skill lives on which agent, which can write) |
| step 11 | `src/m05_a2a/orchestrator.py` (`RemoteCrew`, `build_remote_graph`) + `launcher.py` + `cli.py` |
