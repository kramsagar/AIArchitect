# Module 2: Real tools, RAG fundamentals, memory and MCP

Level 1 (Foundations) of the [Agentic AI Architect program](../ROADMAP.md). Builds on [Module 1](../m01-llm-agent-engineering).

**Deliverable:** `observability-mcp-server`, which exposes Prometheus, Jaeger, Splunk, change data and runbook search
over MCP. The M1 agent loop is upgraded into an **MCP-client investigator** that answers "why is checkout slow?" from
live [ShopSphere lab](../../lab) telemetry, with cited and grounded evidence, session memory and episodic memory.

```
             m02 investigate "why is checkout slow?"            Claude Desktop / Claude Code / any MCP host
                         │ (MCP client, stdio or streamable HTTP)            │
                         ▼                                                   ▼
  ┌──────────────── observability-mcp-server (src/m02_obs/server.py) ─────────────────┐
  │ tools: get_slo_status · list_firing_alerts · promql_query · search_traces ·       │
  │        get_trace · search_logs (SPL guardrail) · get_recent_changes ·             │
  │        search_runbooks                                                            │
  │ resources: runbook://{chunk_id} · kb://index     prompts: investigate(symptom)    │
  └──────┬──────────────┬───────────────┬──────────────┬──────────────┬───────────────┘
         │ timeout · retry+jitter · circuit breaker · TTL cache · row caps (backends/)
     Prometheus      Jaeger         Splunk REST     ShopSphere       RAG knowledge base
     :9090           :16686         :8090           /api/chaos       runbooks · postmortems ·
                                                                     architecture · SLO policy
  Investigator (agent.py): broad → runbook → drill down → Investigation JSON → ground() drops unverifiable citations
  Memory (memory.py): session window + summary · SQLite facts (TTL) · episodic incidents (embedded) · redaction
```

## Study plan (about 5 hours)
| # | Topic | Theory | Lab |
|---|---|---|---|
| 1 | Real tools over real backends: timeouts, retries, breakers, shaping, guardrails | [01](theory/01-real-tools.md) | `python -m m02_obs.labs.l01_real_tools [--live]` |
| 2 | RAG: chunking, embeddings, similarity | [02](theory/02-rag-fundamentals.md) | `python -m m02_obs.labs.l02_chunk_embed` |
| 3 | Vector search, metadata filters, retrieval eval | [02](theory/02-rag-fundamentals.md) | `python -m m02_obs.labs.l03_vector_search` |
| 4 | Memory: session, long-term, episodic | [03](theory/03-memory.md) | `python -m m02_obs.labs.l04_memory` |
| 5 | Model Context Protocol | [04](theory/04-mcp.md) | `python -m m02_obs.labs.l05_mcp` |
| 6 | Grounded investigation with citations | [05](theory/05-grounded-investigation.md) | `python -m m02_obs.labs.l06_investigator` |

Reading: [MCP specification](https://modelcontextprotocol.io/specification) ·
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) ·
[Anthropic: contextual retrieval](https://www.anthropic.com/news/contextual-retrieval) ·
[pgvector](https://github.com/pgvector/pgvector) · Google SRE Workbook, "Alerting on SLOs".

## Setup (Windows PowerShell)
```powershell
cd learning\m02-rag-memory-mcp
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ..\m01-llm-agent-engineering -e ".[dev]"     # add ,embeddings for sentence-transformers
pytest -q                                                    # offline, no key, no lab needed
```
Linux/macOS: `python3.12 -m venv .venv && source .venv/bin/activate`, then the same `pip` line.

## Run it
Offline first (fixtures plus a scripted mock LLM, free):
```powershell
m02 index                                     # chunks and metadata
m02 search "payments latency made checkout slow" --type postmortem
m02 eval                                      # recall@3 and MRR
m02 tools                                     # what the MCP server exposes
m02 --scenario checkout-latency investigate "why is checkout slow?" --trace
m02 --scenario payments-outage investigate "why are orders failing?" --trace
```
Live lab plus Claude (start the lab first with `cd lab; docker compose up -d`):
```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."         # or setx once, then open a new window
curl.exe -X POST localhost:8080/api/chaos/scenarios/checkout-latency   # break something
# wait 2-3 minutes for the 5m windows and alerts
m02 --backend live --provider anthropic investigate "why is checkout slow?" --trace
m02 --backend live --provider anthropic chat  # multi-turn, session memory
curl.exe -X POST localhost:8080/api/chaos/scenarios/reset
```
`--model claude-haiku-5-5` is cheaper and faster. One investigation is about 4–6 LLM calls.

Remote MCP server (streamable HTTP) that several hosts can share:
```powershell
m02 --backend live serve --transport streamable-http --port 8765     # http://localhost:8765/mcp
m02 tools --mcp-url http://localhost:8765/mcp
m02 --provider anthropic investigate "why is checkout slow?" --mcp-url http://localhost:8765/mcp
```

Use it from Claude Desktop or Claude Code (`claude_desktop_config.json` / `.mcp.json`):
```json
{"mcpServers": {"observability": {"command": "C:/path/to/.venv/Scripts/python.exe",
  "args": ["-m", "m02_obs.server"], "env": {"OBS_BACKEND": "live"}}}}
```

Memory: `m02 memory` (show), `m02 memory --remember payments_timeout 2s`, `m02 memory --clear`. Stored in `~/.m02/memory.db`
(override with `M02_MEMORY_DB`). Disable it per run with `--no-memory`.

## Configuration (environment variables; see `.env.example`)
`OBS_BACKEND` (fixture|live) · `OBS_FIXTURE_SCENARIO` (checkout-latency|payments-outage|healthy) · `PROMETHEUS_URL` ·
`JAEGER_URL` · `SPLUNK_URL` (management API, lab host port 8090) · `SPLUNK_USERNAME` / `SPLUNK_PASSWORD` ·
`SHOP_URL` · `OBS_TIMEOUT_S` · `ANTHROPIC_API_KEY` · `AGENT_MODEL`. The package does not load `.env` files; set the
variables in your shell.

## Code map
| Path | What |
|---|---|
| `backends/http.py` | `BackendClient`: httpx with timeout, retry plus jitter, circuit breaker and TTL cache (reuses M1 resilience) |
| `backends/prometheus.py` · `jaeger.py` · `splunk.py` · `chaos.py` | shaped, capped, read-only views of each backend; `validate_spl` guardrail |
| `backends/fixtures.py` | offline incidents with the same shapes as live |
| `rag/` | chunker, embedders (hashing, sentence-transformers), vector store with filters, knowledge base and retrieval eval |
| `corpus/` | architecture, postmortems and SLO policy; lab runbooks come from `lab/docs/runbooks.md` |
| `memory.py` | session memory, SQLite facts and episodes, redaction |
| `server.py` | the MCP server: tools, resources, prompts, stdio, streamable HTTP |
| `agent.py` · `llm.py` · `schemas.py` · `prompts.py` | MCP-client investigator, Claude and mock LLMs, `Investigation` contract, `ground()` |
| `cli.py` | `m02` command |

## Check yourself (module exit)
1. Draw the path of one `search_logs` call from the LLM's tool call to Splunk and back, and name every control on it.
2. `get_slo_status` shows checkout p95 at 2.2 s and the shop at 5% CPU. Which tool do you call next, and why not "scale up"?
3. Why does `ground()` check identifiers verbatim instead of asking another LLM "is this grounded?"
4. Retrieval recall@3 drops from 1.0 to 0.7 after you change chunk size. What do you do before shipping?
5. What changes when the MCP server moves from stdio on a laptop to streamable HTTP shared by 30 teams?

Next: **M3 Agentic RAG** (hybrid search, reranking, query rewriting, self-correcting retrieval over this knowledge base).
