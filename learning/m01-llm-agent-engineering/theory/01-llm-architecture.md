# 1. LLM architecture for engineers: tokens, context, embeddings, temperature

> Lab: `python -m m01_agent.labs.l01_llm_basics`

## Mental model
An LLM is a **stateless function**: `next_token_distribution = f(all tokens so far)`.
Everything else (chat, memory, tools, agents) is software *you* build around that function.
That framing is the single most important idea for an architect.

```
text -> tokenizer -> token ids -> [transformer: attention over the whole context] -> logits -> sampling -> token
                                                                                      ^ temperature/top_p
```

## Tokens
- Unit of **cost, latency and limits**. ~4 chars or ~0.75 English words per token; logs, JSON, UUIDs, IPs and stack traces tokenize **worse** (more tokens per char).
- Input tokens are processed in parallel (prefill, drives time-to-first-token, TTFT). Output tokens are generated one at a time (decode, drives total latency). **Output tokens are the latency budget killer**; cap `max_tokens` and keep answers structured and short.
- SRE translation: a log line ≈ 40 tokens. 12k RPS × 0.4% errors ≈ 4.3M error lines/day ≈ 170M tokens/day. You never send raw logs to an LLM at scale: **aggregate, template, sample, then send** (the lab computes this).

## Context window
- Max tokens of (instructions + history + tool results + output) per call. Bigger is not free: cost and TTFT scale with input, and models attend less reliably to the middle of long contexts ("lost in the middle").
- Treat the context window like **memory on a pod with a hard limit**: budget it explicitly (system/dev ~10%, task ~5%, evidence ~60%, history ~15%, reserved output ~10%).
- Overflow strategies: truncate oldest turns, summarise, retrieve only relevant chunks (RAG, module 2), push facts into a structured "state" block.

## Embeddings
- A model that maps text to a vector; semantically similar text ends up close (cosine similarity).
- Uses in ops: dedupe/cluster alerts, find similar past incidents, retrieve runbooks (RAG), semantic cache keys (module 10).
- Embeddings ≠ understanding: "latency **not** high" and "latency high" are close. Always combine with keyword/filters (hybrid search, module 3).

## Temperature, top_p, determinism
- Logits are divided by temperature before softmax. `T→0` ≈ greedy (most likely token); higher `T` flattens the distribution (more diverse, more wrong).
- **Agents, tool selection, extraction, classification: T=0.** Brainstorming hypotheses: 0.7–1.0 with several samples, then verify with tools.
- Provider reality: the newest Claude models no longer accept `temperature` (fixed sampling), so the M1 Claude
  adapter never sends it. Determinism must come from **tight instructions, schemas, tool results and evals**.
- T=0 is *not* bit-for-bit deterministic in hosted APIs (batching, floating point). Design for **repeatable behaviour via validation and evals**, not via sampling settings.

## Model selection as an architect
| Concern | Lever |
|---|---|
| Latency | smaller model, fewer output tokens, streaming, prompt caching (stable prefix) |
| Cost | route easy requests to small model, cache, trim context |
| Quality | bigger/reasoning model only on hard paths, better context, evals |
| Reliability | timeouts, retries, fallback model/provider, degrade to rules |

## Check yourself
1. Why does a 2k-token answer hurt p99 more than a 20k-token prompt?
2. Estimate daily tokens for sending every WARN line of a 5k RPS service at 2% warn ratio.
3. When would you *want* temperature > 0 in an SRE agent?
