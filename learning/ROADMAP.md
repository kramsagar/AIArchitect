# Agentic AI Architect program: basic → hero (SRE / observability edition)

**Goal:** design, build, evaluate, secure, deploy and operate enterprise multi-agent systems, and be able to defend every
architectural decision in a design review or interview.

**Why this track works for you:** SRE thinking (SLOs, timeouts, retries, blast radius, observability, change management)
*is* production agent engineering. Every module uses incidents, telemetry and capacity problems, and from module 2 onward
agents work against a **real instrumented system**: the [ShopSphere observability lab](../lab/).

## How each module is built
| Part | What you get |
|---|---|
| Theory | crisp notes per topic, with architecture diagrams and trade-off tables |
| Labs | small runnable scripts, one per concept, offline by default |
| Deliverable | a production-shaped project with tests, CI, mock mode + OpenAI mode |
| Check yourself | questions you should answer without notes |
| Exercises | extensions that force you to change the design |
| Reading | primary sources only |

Rules for every module: demo/mock mode, no secrets in Git, `ruff` + `pytest` in CI, telemetry for the agent itself.
Default LLM: **Claude** (`ANTHROPIC_API_KEY`); OpenAI supported as an alternative. Embeddings: local
sentence-transformers (Anthropic has no embeddings API; Voyage AI optional).

## The lab everything runs against
```
           load generator (k6/locust)       chaos API (latency, errors, slow DB, CPU, dependency down)
                       │                              │
                       ▼                              ▼
     ShopSphere (FastAPI): auth · catalog · search · cart · checkout · payments ──> Postgres, Redis
                       │ OTLP (traces, metrics, logs)
                       ▼
              OpenTelemetry Collector
          ┌────────────┼──────────────┬───────────────┐
          ▼            ▼              ▼               ▼
     Prometheus     Jaeger (APM)   Splunk (HEC)    (Langfuse, M7)
     + SLO rules        │              │
          └──────── Grafana ───────────┘
                       ▲
          agents (M2+) query Prometheus / Jaeger / Splunk / runbooks through tools and MCP
```

## Level 1: Foundations
### M1. LLM & agent engineering ✅ [`m01-llm-agent-engineering`](m01-llm-agent-engineering/)
- **Theory:** tokens, context window, embeddings, temperature · instruction hierarchy · prompt vs context engineering ·
  structured outputs · function calling · agent loop · state, memory, retries, timeouts, circuit breakers.
- **Deliverable:** SRE copilot, a single agent with `get_service_health` and `capacity_calculator`, strict Pydantic output,
  repair loop, budgets, bench (p50/p95/p99, RPS). Providers: mock, Claude, OpenAI. Same agent on the OpenAI Agents SDK.

### M2. Real tools, RAG fundamentals, memory and MCP ✅ [`m02-rag-memory-mcp`](m02-rag-memory-mcp/)
- **Theory:** chunking strategies, embedding models, vector DBs (pgvector, Chroma, FAISS), similarity metrics, metadata
  filters · short-term/long-term/episodic memory, summarisation · tool design for real backends · Model Context Protocol
  (hosts, clients, servers, tools/resources/prompts, transports, auth).
- **Labs:** PromQL tool over lab Prometheus · Jaeger trace search tool · Splunk SPL search tool · runbook ingestion and
  retrieval · memory store in Postgres/Redis.
- **Deliverable:** `observability-mcp-server` exposing Prometheus, Jaeger, Splunk and runbook search over MCP; the M1
  agent upgraded to answer "why is checkout slow?" from live lab telemetry, with cited evidence.

## Level 2: Practitioner
### M3. Agentic RAG ✅ [`m03-agentic-rag`](m03-agentic-rag/)
- **Theory:** naive RAG failure modes · hybrid search (BM25 + vectors) · reranking · query rewriting/decomposition ·
  HyDE · self-RAG / corrective RAG · retrieval as a tool · citations and grounding · GraphRAG (service dependency graph).
- **Deliverable:** incident-knowledge agent over runbooks, postmortems and architecture docs that decides when and what to
  retrieve, grades its own retrieval and re-queries; measured with retrieval metrics (recall@k, MRR).

### M4. Multi-agent workflows with LangGraph ✅ [`m04-multi-agent`](m04-multi-agent/)
- **Theory:** workflow vs agent vs multi-agent · supervisor, hierarchical, swarm/handoff patterns · state graphs,
  reducers, checkpoints · human-in-the-loop interrupts · durable execution and replay · when *not* to go multi-agent.
- **Deliverable:** incident-response crew: triage → telemetry investigator → RCA → remediation planner → **human approval**
  → executor (lab chaos API rollback) → postmortem writer. Checkpointed in Postgres, resumable after crash.

### M5. Agent-to-agent (A2A) and interoperability ✅ [`m05-a2a`](m05-a2a/)
- **Theory:** A2A protocol (agent cards, tasks, messages, artifacts, streaming), MCP vs A2A, discovery, trust and auth
  between agents, contracts and versioning, async/long-running tasks, cross-framework agents.
- **Deliverable:** M4 agents split into independently deployed A2A services (e.g. an SDK-based capacity agent called by a
  LangGraph supervisor), with service discovery, timeouts and tracing across agent hops.

## Level 3: Professional
### M6. Evaluation engineering
- **Theory:** eval taxonomy (unit, component, trajectory, end-to-end) · golden datasets from real incidents · deterministic
  checks vs LLM-as-judge (bias, calibration) · RAG metrics (Ragas: faithfulness, context precision/recall) · tool-call
  accuracy · regression gates · online evals and feedback · statistical significance.
- **Deliverable:** eval harness with 50+ golden incidents generated by injecting faults into the lab; CI gate that blocks a
  prompt/model change if RCA accuracy, faithfulness or cost regresses.

### M7. AgentOps and observability of agents
- **Theory:** OpenTelemetry GenAI semantic conventions · traces across LLM/tool/agent spans · Langfuse · token, cost,
  latency and error SLOs for agents · drift and quality monitoring · prompt/model versioning · incident response for AI.
- **Deliverable:** every agent exports OTel traces to the lab collector and Langfuse; Grafana "Agent SLO" dashboard
  (TTFT, p95 run latency, tool error rate, cost per incident, eval score) with burn-rate alerts.

### M8. Guardrails, safety and security
- **Theory:** OWASP Top 10 for LLM apps · direct/indirect prompt injection · tool permissioning and least privilege ·
  RBAC/ABAC per tool · PII detection and redaction · output validation · sandboxing · secrets management · audit trails ·
  red teaming · NIST AI RMF / EU AI Act basics.
- **Deliverable:** policy layer (input/output/tool guardrails, approval policies, redaction of logs from Splunk), audit log,
  and an automated red-team suite run in CI.

## Level 4: Architect / hero
### M9. Production engineering and deployment
- **Theory:** agent service architecture (API, workers, queues, state stores) · sessions and idempotency · streaming
  (SSE) · async workers · config and feature flags · containerisation · Kubernetes/OpenShift (probes, HPA, PDB,
  NetworkPolicy) · Helm · GitOps · CI/CD with eval gates · canary/shadow releases for prompts and models · quotas and
  rate limits.
- **Deliverable:** the AI-SRE platform packaged as FastAPI + workers, Helm chart, kind/OpenShift deploy, GitHub Actions
  pipeline: lint → tests → evals → image → deploy → canary analysis.

### M10. Low latency and high TPS
- **Theory:** latency anatomy (queue, TTFT, decode, tools) · streaming · parallel tool calls · prompt caching · exact and
  semantic caching · model routing and cascades · batching · small/fine-tuned models · vLLM serving · backpressure,
  load shedding, concurrency limits · provider rate limits and multi-provider failover · cost/latency budgets.
- **Deliverable:** load test (k6/Locust) of the platform at target TPS with p99 budget; before/after report showing the
  impact of each optimisation; graceful degradation under provider outage.

### M11. Enterprise architecture
- **Theory:** reference architectures (gateway, orchestration, tools, knowledge, memory, observability, governance planes) ·
  multi-tenancy and isolation · HA/DR and multi-region · data residency · model governance and registry · FinOps for
  LLMs · build vs buy · ADRs · threat modelling · production readiness reviews · operating model (platform team, AI CoE).
- **Deliverable:** architecture pack for the AI-SRE platform: C4 diagrams, 10 ADRs, threat model, risk register,
  SLOs, capacity and cost model, DR plan, readiness checklist.

### M12. Capstone: autonomous AI-SRE platform
- Inject faults into ShopSphere under load; the platform detects (burn-rate alert), triages, investigates across
  Prometheus/Jaeger/Splunk, retrieves runbooks, proposes and (after approval) executes remediation, verifies recovery
  against the SLO and writes the postmortem. Evaluated, guarded, observed, deployed via CI/CD.
- **Defend it:** 45-minute design review + mock system design interview using your own ADRs.

## Suggested pace
| Track | Pace |
|---|---|
| Intensive | 1 module / week (≈12 weeks) |
| Part-time | 1 module / 2 weeks |
Each module ≈ 25% theory, 50% labs/deliverable, 25% exercises and review.

## Primary reading
- Anthropic: [Tool use](https://docs.claude.com/en/docs/agents-and-tools/tool-use/overview), [Structured outputs](https://docs.claude.com/en/docs/build-with-claude/structured-outputs), [Prompt caching](https://docs.claude.com/en/docs/build-with-claude/prompt-caching), [Building effective agents](https://www.anthropic.com/research/building-effective-agents)
- OpenAI: [Agents SDK](https://openai.github.io/openai-agents-python/), [Function calling](https://platform.openai.com/docs/guides/function-calling), [Structured outputs](https://platform.openai.com/docs/guides/structured-outputs)
- [Model Context Protocol](https://modelcontextprotocol.io) · [A2A protocol](https://a2a-protocol.org)
- [LangGraph docs](https://langchain-ai.github.io/langgraph/)
- [Ragas](https://docs.ragas.io) · [Langfuse](https://langfuse.com/docs)
- [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [OWASP Top 10 for LLM Applications](https://genai.owasp.org/llm-top-10/) · [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)
- Google SRE book: [Handling overload](https://sre.google/sre-book/handling-overload/), [Addressing cascading failures](https://sre.google/sre-book/addressing-cascading-failures/)
