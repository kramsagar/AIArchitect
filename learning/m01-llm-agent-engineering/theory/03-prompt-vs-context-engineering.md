# 3. Prompt engineering vs context engineering

> Lab: `python -m m01_agent.labs.l03_context_engineering` · Code: `agent.py: build_context`, `memory.py`

**Prompt engineering** = wording of instructions (role, rules, examples, output format).
**Context engineering** = deciding *what information* goes into the window, *in what form*, *at what time*, within a token budget. It is a systems problem, and it is where most quality, cost and latency wins come from.

| | Prompt engineering | Context engineering |
|---|---|---|
| Unit | a string | a pipeline |
| Question | "How do I ask?" | "What does the model need to know right now?" |
| Inputs | instructions, few-shot | state, memory, retrieved docs, tool results, schemas, history |
| Failure | ambiguous ask | missing evidence, stale data, noise, overflow, injection |
| Owner | anyone | architect / platform |

## The context assembly pipeline (what `build_context` does)
1. **Instructions**: system + developer (stable prefix → cacheable).
2. **State**: compact facts (`last_service=checkout-api`) instead of the whole transcript.
3. **Memory**: last N turns within a token budget.
4. **Task**: user message.
5. **Evidence**: tool results, compacted (aggregate numbers, not raw dumps).

Selection techniques for incidents: rank evidence by signal (errors > latency > deploy events > info logs), dedupe, template logs (`user <*> timed out after <*>ms`), keep exact numbers, drop healthy noise, cite source/timestamp.

## Rules of thumb
- Less, better context beats more context.
- Structured > prose: `{"p99_ms": 2100, "slo_p99_ms": 800}` is cheaper and less ambiguous.
- Tool results are context too: design tool outputs for the model (small, labelled, with units).
- Measure: tokens per request, retrieval hit rate, answer quality (evals). Context engineering without evals is guessing.

## Check yourself
1. You have 4k tokens for evidence and 300 log lines of 40 tokens. Describe your reduction strategy.
2. Why store `last_service` as a fact rather than relying on chat history?
