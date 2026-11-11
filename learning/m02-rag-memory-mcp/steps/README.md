# Module 2, step by step: real tools, RAG, memory and MCP

Same approach as the [Module 1 steps](../../m01-llm-agent-engineering/steps/README.md). There are **12 small runnable files**, and
each one adds one idea. After step 11 you have built the Module 2 deliverable yourself: an MCP-based investigator that answers
"why is checkout slow?" from live lab telemetry, with cited evidence.

Each step has four parts: **Run it**, **What's new** (`git diff --no-index` against the previous step), **Build it yourself**
(add the layer to your own `steps/my_obs.py`) and **Check yourself**.

## Setup (once)
```powershell
cd learning\\m02-rag-memory-mcp
py -3.12 -m venv .venv ; .\\.venv\\Scripts\\Activate.ps1
pip install -e ..\\m01-llm-agent-engineering -e ".[dev]"
copy ..\\m01-llm-agent-engineering\\.env .env      # ANTHROPIC_API_KEY=... (AGENT_MODEL optional, default claude-haiku-5-5)
pytest -q tests\\test_steps.py                      # offline, no lab, no key
```
**Live or offline:** if the lab is running (`cd lab; docker compose up -d`), the steps use real Prometheus, Jaeger and Splunk.
If it isn't, they automatically use an offline checkout-latency incident. To force offline mode, run `$env:OBS_BACKEND = "fixture"`.
For an interesting live run, break something first with `curl.exe -X POST localhost:8080/api/chaos/scenarios/payments-flaky`.
Wait 2–3 minutes, and run `.../scenarios/reset` when you're done.

## The map
| Step | File | New idea | Theory |
|---|---|---|---|
| 0 | `step00_promql.py` | Prometheus HTTP API, recording rules, **shaping** raw JSON | [01](../theory/01-real-tools.md) |
| 1 | `step01_resilient_client.py` | one pooled client: timeout, retry 5xx only, fail fast on 4xx, breaker, cache (reuses `m01_agent.resilience`) | 01 |
| 2 | `step02_jaeger.py` | trace search, span tree → bottleneck (`slowest_spans`) | 01 |
| 3 | `step03_splunk.py` | SPL over REST + a **read-only guardrail** on queries the model writes | 01 |
| 4 | `step04_obs_agent.py` | the M1 agent loop with real tools; coarse vs fine tools; result caps | 01 |
| 5 | `step05_chunking.py` | RAG: structure-aware chunks, stable ids (`runbooks#checkout-latency`), metadata | [02](../theory/02-rag-fundamentals.md) |
| 6 | `step06_vector_search.py` | embeddings, cosine, top-k, metadata filters | 02 |
| 7 | `step07_retrieval_eval.py` | recall@k and MRR, comparing design choices | 02 |
| 8 | `step08_memory.py` | long-term facts (SQLite + TTL), episodic memory, redaction | [03](../theory/03-memory.md) |
| 9 | `step09_mcp_server.py` | MCP server: tools, resources, prompts (FastMCP) | [04](../theory/04-mcp.md) |
| 10 | `step10_mcp_client.py` | MCP client over stdio: initialize, discover tools at runtime, call them | 04 |
| 11 | `step11_investigator.py` | Claude + MCP tools + `Investigation` JSON + **grounding** + episodic memory = M2 | [05](../theory/05-grounded-investigation.md) |

---
## Step 0: PromQL over HTTP
**Run:** `python steps\\step00_promql.py` (or pass your own PromQL in quotes).
**What's new:** `GET /api/v1/query?query=...` returns `data.result[{metric, value:[ts, "v"]}]`. `prom_query()` turns that into
`[{labels, value}]`, drops NaN, caps it at 20 series and flags truncation. The queries use the lab's recording rules
(`shopsphere:http_latency_seconds:p95_5m` ...) from `lab/prometheus/rules/slo.yml`.
**Build it yourself:** in `my_obs.py`, write `prom_query(promql)` with `httpx.get(..., timeout=5)` and print the checkout p95.
**Check yourself:** why shape and cap results for an LLM? What does NaN mean here?

## Step 1: a resilient client
**Run:** `python steps\\step01_resilient_client.py`. You'll see that the second call is a cache hit (0 ms), bad PromQL gives a 400 with no retry,
and a dead backend is tried 3 times and then fails.
**What's new:** `Backend` wraps one `httpx.Client` with `retry_call`, `CircuitBreaker` and `TTLCache` from **Module 1**. 5xx, 429
and connection errors are `TransientToolError` and get retried. Other 4xx are `ToolError` and are not retried.
**Build it yourself:** wrap your `prom_query` in a retry plus a 5 s cache. Point it at port 9 and watch the attempts.
**Check yourself:** why is a 400 never retried? Why create ONE client instead of one per call?

## Step 2: Jaeger traces
**Run:** `python steps\\step02_jaeger.py`
**What's new:** `/api/services` and `/api/traces?service=&operation=&minDuration=`. `summarize()` maps `processID` to the service,
converts µs to ms, and picks out the root span, the error spans and the 3 slowest child spans.
**Build it yourself:** write `search_traces(service)`. Then, with `checkout-latency` chaos on, find a checkout over 1 s and its slowest span.
**Check yourself:** what does it mean when a slow trace has no slow child span? (Hint: think about the `checkout-latency` chaos.)

## Step 3: Splunk, safely
**Run:** `python steps\\step03_splunk.py`. One read-only search succeeds, and `| delete`, `index=_audit` and `| rest` are all denied.
**What's new:** `validate_spl()` treats the model's query like user input. The query must name an allowed index, can't start
with `|`, can't use macros, and can't use write or exec commands. The search itself is `POST /services/search/jobs/export` with time bounds and `head`.
**Build it yourself:** write your own `validate_spl` and test 3 bad queries. Then search `index=main trace_id=<id from step 2>`.
**Check yourself:** why is a read-only API account not enough on its own? What else would you limit in production?

## Step 4: the agent with real tools
**Run:** `python steps\\step04_obs_agent.py` (pass your own question in quotes)
**What's new:** 4 tools. The coarse `get_slo_status` is the place to start, and `promql_query`, `search_traces` and `search_logs` are the fine ones.
Tool results are capped at 6000 chars, and errors are returned as `is_error`. The system prompt teaches a method: broad first, then drill down.
**Build it yourself:** register your three functions as Claude tools and reuse your Module 1 loop.
**Check yourself:** why does the coarse tool reduce cost and hallucination? Where should the result cap live?

## Step 5: chunking
**Run:** `python steps\\step05_chunking.py`
**What's new:** each `## section` of `lab/docs/runbooks.md`, the architecture doc, the postmortems and the SLO policy becomes one `Chunk`, with a stable id,
a heading path in the text, and `type`/`alerts`/`services` metadata.
**Build it yourself:** chunk the runbooks yourself and print the ids.
**Check yourself:** why split on headings instead of every N characters? Why do citations need stable ids?

## Step 6: vector search
**Run:** `python steps\\step06_vector_search.py` (pass your own query in quotes)
**What's new:** `embed()` (word and pair hashing, then L2 normalisation), `cosine()`, and `VectorStore.search(query, k, filters)`.
**Build it yourself:** embed your chunks and search "payments returning 503".
**Check yourself:** what does this embedder miss? (Try a synonym: "purchase takes forever".) What would pgvector or FAISS change?

## Step 7: retrieval evaluation
**Run:** `python steps\\step07_retrieval_eval.py`
**What's new:** 5 labelled questions, scored with recall@k ("is the right chunk in the top k?") and MRR ("how high is it ranked?"). It also compares k and chunk size.
**Build it yourself:** add 3 questions of your own, including one that fails, and fix it, for example by improving `tokens()`.
**Check yourself:** why measure retrieval separately from the final answer?

## Step 8: long-term and episodic memory
**Run:** `python steps\\step08_memory.py`
**What's new:** SQLite `facts` with a TTL, and `episodes` (question + root cause, embedded) recalled by similarity with a
`min_score` threshold. `redact()` runs before every write.
**Build it yourself:** store a fact with a TTL, record 2 incidents, and recall them with a new wording.
**Check yourself:** what is memory poisoning? Why redact before storing, and not when reading?

## Step 9: MCP server
**Run:** `python steps\\step09_mcp_server.py` for the in-process demo. With `--serve` it runs as a real stdio server.
**What's new:** `FastMCP` with `@mcp.tool` (marked read-only), `@mcp.resource("runbook://{chunk_id}")` and `@mcp.prompt`. The tool
schemas are generated from the Python type hints.
**Build it yourself:** expose your own two functions as MCP tools and list them.
**Check yourself:** what's the difference between a tool, a resource and a prompt? Why standardise this?

## Step 10: MCP client
**Run:** `python steps\\step10_mcp_client.py`
**What's new:** `stdio_client(StdioServerParameters(...))` starts step 9 as a subprocess. Then `initialize`, `list_tools` (discovered at
runtime), `call_tool`, and `to_claude_tools()` maps each MCP schema 1:1 to a Claude tool spec.
**Build it yourself:** connect to your server from step 9 and call one tool.
**Check yourself:** what changes if the server runs remotely over streamable HTTP? Who authenticates whom?

## Step 11: the investigator (= Module 2)
**Run:** `python steps\\step11_investigator.py`. Run it twice: the second run recalls the first incident from `investigations.db`.
**What's new:**
- The `Investigation` schema, with `evidence[{source, ref, finding}]`.
- Parallel tool calls through `asyncio.gather`.
- `ground()`, which drops evidence whose `ref` never appeared in a tool result.
- A fallback when the output is invalid, and episodic memory that is written after each run and read before the next.

**Build it yourself:** combine your steps 4, 8 and 10. Your agent should now cite the trace ids and runbook ids it actually saw.
**Check yourself:** why check ids literally instead of asking another LLM "is this grounded?"

---
## From your build to the production code (`src/m02_obs/`)
| Step | Production | Adds |
|---|---|---|
| 0–3 | `backends/prometheus.py`, `jaeger.py`, `splunk.py`, `http.py` | more shapes (alerts, SLO view), a full deny-list, field caps, a changes backend (`chaos.py`) |
| offline mode | `backends/fixtures.py` | 3 scenarios (`checkout-latency`, `payments-outage`, `healthy`) with live-shaped data |
| 4 | `server.py` tool set | 8 tools, including `get_trace`, `list_firing_alerts` and `get_recent_changes` |
| 5–7 | `rag/chunking.py`, `embeddings.py`, `store.py`, `index.py` | long-section splitting with overlap, optional sentence-transformers, JSON persistence, 10-question eval |
| 8 | `memory.py` | `SessionMemory` with a rolling summary, more redaction rules |
| 9–10 | `server.py`, `cli.py` (`m02 serve`, `m02 tools`) | streamable HTTP transport, `kb://index` resource |
| 11 | `agent.py`, `llm.py`, `schemas.py`, `prompts.py` | Claude strict JSON schema, a mock LLM for CI, budgets and deadline, a repair loop, a richer `ground()` |

Then try the real thing: `m02 --backend live --provider anthropic investigate "why is checkout slow?" --trace`.
