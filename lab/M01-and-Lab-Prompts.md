# Prompts for NotebookLM and Gemini: study Module 1 + the ShopSphere lab

## How to set up
**NotebookLM** (notebooklm.google.com): create a new notebook and add these sources:
1. `M01-and-Lab-Design-Guide.md` (architecture, diagrams, walkthroughs)
2. `M01-and-Lab-Source-Bundle.txt` (all the real code and config)
3. Optional: the website https://github.com/kramsagar/AIArchitect, and https://openai.github.io/openai-agents-python/
Then paste the prompts below into the chat, one at a time. Use **Audio Overview** with the customization prompt in section 7.

**Gemini** (gemini.google.com, 2.5 Pro or newer): upload both files in one chat. Gemini renders Mermaid if you ask for
"a Mermaid code block". Paste each output into https://mermaid.live to view and export the diagrams as PNG/SVG.

Start every new chat with the **context primer**:
> You are my senior staff engineer and mentor for agentic AI and SRE. The attached sources contain my repository:
> Module 1 (an SRE Copilot agent in Python with two tools, Pydantic structured output, retries, timeouts, a circuit breaker
> and memory, using Claude) and the ShopSphere observability lab (FastAPI shop + payments, Postgres, Redis, OpenTelemetry
> Collector, Prometheus, Jaeger, Splunk, Grafana, Locust, chaos API). Answer ONLY from the sources; quote the file path and
> function name for every claim; say "not in the sources" if something isn't there. Teach me step by step; I'm moving
> from beginner to enterprise architect.

---
## 1. Diagrams (ask for Mermaid)
1. "Draw a Mermaid **component diagram** of `m01_agent`: every module in `src/m01_agent`, what it imports, and the
   direction of dependencies. Group into: interface (cli), wiring (factory/config), core (agent, prompts, memory, schemas),
   tools (registry, service_health, capacity), infrastructure (resilience, telemetry, tokens), LLM adapters."
2. "Draw a Mermaid **flowchart of `Agent.run`** covering every branch: deadline expiry, LLMError, tool-budget exceeded,
   duplicate call, invalid output → repair, max_repairs, max_steps, grounding, memory save, fallback. Label each exit
   with its `RunStatus`."
3. "Draw a Mermaid **sequenceDiagram** for the question 'Can checkout-api handle 2x traffic?' with the Claude provider:
   CLI → factory → Agent → AnthropicLLM (show `to_anthropic` translation) → Claude API → ToolRegistry → TTLCache →
   CircuitBreaker → call_with_timeout → MockMetricsBackend / calculate → back to the final AssistantResponse."
4. "Draw a Mermaid **state diagram** of `CircuitBreaker` (closed/open/half_open) with the exact transition conditions from
   `resilience.py`."
5. "Draw a Mermaid **class diagram** of the Pydantic models in `schemas.py` and `llm/base.py` and how they nest
   (`AgentResult` → `StepTrace` → `ToolCall`/`Observation`, `AssistantResponse`, `Usage`, `LLMDecision`)."
6. "Draw a Mermaid **deployment diagram** of `lab/docker-compose.yml`: every container, image, host port, internal port,
   depends_on/healthcheck, and resource limits."
7. "Draw a Mermaid **data-flow diagram** of the telemetry pipeline from `lab/otel-collector/config.yaml`: receivers,
   processors, the spanmetrics connector, exporters and which backend each signal lands in."
8. "Draw a Mermaid **sequenceDiagram** of `POST /api/checkout` in `lab/shopsphere/app/main.py`, including every Redis
   key, the SQL transaction span, the HTTP call to payments, the timeout, every error response code it can return, and the
   metrics and logs emitted."
9. "Draw one Mermaid diagram showing how a single checkout's `trace_id` flows: created by FastAPI instrumentation,
   propagated by HTTPX to payments, exported via OTLP, and visible in Jaeger, in Prometheus exemplars and in Splunk logs."

## 2. Code walkthrough (one file at a time)
* "Walk me through `agent.py` line by line like a code review. For each block: what it does, why it's needed in
  production, what would break without it, and one test in `tests/test_agent.py` that proves it."
* Repeat for: `tools/registry.py`, `resilience.py`, `llm/anthropic_llm.py`, `tools/capacity.py`, `memory.py`,
  `jsonschema.py`, `prompts.py`, `lab/shopsphere/app/main.py`, `lab/shopsphere/app/chaos.py`, `lab/shopsphere/app/telemetry.py`.
* "Explain `strict_json_schema` with a before/after example of the JSON schema for `ServiceHealthArgs`."
* "Show exactly what messages list Claude receives at step 2 of the 2x-traffic question, after `to_anthropic`
  translation. Write it as JSON."

## 3. Design reasoning (architect level)
* "List every design decision in Module 1 as an ADR (Architecture Decision Record): context, decision, alternatives
  considered, consequences. At least 10 ADRs (e.g. provider-neutral LLM protocol, mock LLM, AST calculator, strict schemas,
  grounding tools_used, retry only idempotent tools, deadline propagation, token-budgeted memory)."
* "What are the failure modes of this agent in production? Make an FMEA table: failure, cause, detection (which
  log/metric/span), mitigation already in code, remaining risk."
* "Compare the hand-written loop in `agent.py` with the OpenAI Agents SDK version in `sdk_agent.py`. What does the
  framework give you, what do you lose, and when would you pick each in an enterprise?"
* "If this agent had to serve 1,000 requests per second, where are the bottlenecks? Use `cmd_bench`, `TTLCache`,
  `call_with_timeout`'s thread pool and LLM latency. Propose changes."
* "Review the lab architecture like an SRE: single points of failure, missing controls, what you would change for a
  real production deployment on Kubernetes."

## 4. Trace a real run
Paste your own `--trace` output and ask:
> "Here is my real run output: <paste>. Explain each step: which code ran, what the model saw, why it chose these tool
> calls, how 63 replicas and the 8.4x burn rate were computed (show the formulas from `capacity.py`), and why severity is
> CRITICAL according to `DEVELOPER_PROMPT`."

## 5. Hands-on exercises (ask it to grade you)
* "Give me 5 coding exercises on Module 1 with increasing difficulty (e.g. add a third tool `get_recent_deploys`, add
  a per-tool rate limiter, make memory summarise old turns, add an OpenTelemetry exporter to `telemetry.py`, add a
  cost budget in dollars to the loop). For each: goal, files to change, acceptance tests. Don't give solutions until I ask."
* "Give me 5 lab drills using the chaos scenarios in `chaos.py`. For each: command, which Grafana panel, Prometheus alert,
  Jaeger search and Splunk SPL to use, what I should observe, and the runbook section that applies."
* "I'll explain how the retry + circuit breaker work; grade my explanation against the code and correct my mistakes."

## 6. Quiz and flashcards
* "Create 30 flashcards (question → answer with file reference) covering tokens, instruction hierarchy, context
  engineering, structured output, function calling, agent loop, retries/timeouts/breaker, memory, OTel, SLOs/burn rate."
* "Quiz me with 10 multiple-choice questions, one at a time, at the level of a senior SRE / AI architect interview.
  Wait for my answer before revealing the correct one."
* "Make a one-page cheat sheet of Module 1 and the lab: commands, ports, key classes, formulas (burn rate, Little's law,
  replicas, error budget)."

## 7. NotebookLM Audio/Video Overview customisation
> "Two senior engineers explain this repository to a learner who wants to become an enterprise agentic-AI architect.
> Part 1: the SRE Copilot agent loop, with the real 'can checkout-api handle 2x traffic?' run as the story. Part 2: how
> ShopSphere emits OpenTelemetry and how a payments-flaky incident shows up in Grafana, Prometheus, Jaeger and Splunk.
> Part 3: how Module 2 turns this into an MCP-based investigator. Name real functions and files; avoid generic AI hype."

Also try NotebookLM's **Mind Map** (structure of the codebase), **Study guide** and **Briefing doc** buttons.
