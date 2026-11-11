# M5 - Agent-to-agent (A2A) interoperability

The M4 incident crew, split into **7 independently served A2A agents** (official `a2a-sdk` 1.x, JSON-RPC binding,
protocol 1.0) and orchestrated by the **unchanged M4 LangGraph graph**.

```
                 orchestrator (LangGraph + checkpoints + HUMAN APPROVAL)
                   │  discover: GET /.well-known/agent-card.json on every registry URL
                   │  call: POST /a2a/jsonrpc SendMessage {skill, state}  (Bearer token, traceparent)
   ┌───────────┬───┴────────────┬──────────────┬──────────────┬──────────────────┬─────────────┐
triage-agent telemetry-agent  knowledge-agent  rca-agent    planner-agent    executor-agent  scribe-agent
  :9101       :9102            :9103            :9104        :9105            :9106 (writes)  :9107
  triage      metrics traces   knowledge(M3)    rca (LLM)    planner (LLM)    executor        postmortem
              logs changes(M2)                                                verifier
```

- Each agent publishes an **Agent Card** (skills, tags `read-only`/`write`, JSON-RPC URL) and serves one or more M4
  `Crew` methods. State goes in as a JSON DataPart; a partial update comes back as an `update` artifact; LangGraph
  reducers merge it exactly as in M4.
- **Discovery by skill**, **bearer auth** (`M05_TOKEN`), **W3C trace propagation** (one trace id per incident),
  **timeouts + retries + graceful degradation**, **least privilege** (agents reject skills they don't own).
- Approval and checkpoints stay in the orchestrator, so specialists are stateless and horizontally scalable.

## Setup (Windows PowerShell)

```powershell
cd learning\m05-a2a
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ..\m01-llm-agent-engineering -e ..\m02-rag-memory-mcp -e ..\m03-agentic-rag -e ..\m04-multi-agent -e ".[dev]"
copy ..\m01-llm-agent-engineering\.env .env
```

## Run it

```powershell
m05 run --spawn --approve                       # offline: starts 7 agents in-process, runs an incident over A2A
m05 serve                                       # terminal 1: all agents (or: m05 serve --agent rca-agent)
m05 cards                                       # terminal 2: discovery
m05 run --approve                               # terminal 2: orchestrate against the running agents
$env:M05_TOKEN="lab-token"                      # set in BOTH terminals to require Bearer auth
m05 --backend live --provider anthropic run --spawn --approve   # live lab + Claude
```

Learn it step by step: [`steps/README.md`](steps/README.md). Theory: [`theory/`](theory/).

## Tests

```powershell
ruff check . ; ruff format --check . ; pytest -q
```
