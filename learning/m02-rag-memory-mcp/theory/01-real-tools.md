# 01 · Real tools over real backends

M1 tools returned mock data. M2 tools call Prometheus, Jaeger, Splunk and the ShopSphere API. Real backends add four
problems the model cannot solve for you: **latency**, **failure**, **volume** and **blast radius**.

## Design rules (each is in `src/m02_obs/backends/`)
| Rule | Why | Where |
|---|---|---|
| Timeout on every call, smaller than the caller's budget | a hung backend must not hang the agent | `http.BackendClient` (httpx timeout) |
| Retry only transient errors (timeout, 429, 502-504), with jittered backoff and a budget | retry storms amplify outages | M1 `retry_call` reused |
| Circuit breaker per backend | stop hammering a backend that is down; fail fast | M1 `CircuitBreaker` |
| Short TTL cache for read queries | an agent asks the same thing several times per run; at high TPS a 5s cache absorbs most load | `cache_ttl_s` |
| **Shape** results: few fields, units, numbers rounded, rows capped | raw Prometheus/Jaeger JSON is 10-100x larger than the facts in it; tokens are latency and money | `PrometheusBackend.slo_status`, `summarize_trace` |
| Read-only by construction + allow-lists | the model's arguments are untrusted input | `splunk.validate_spl` |
| Errors are observations, not exceptions | the model can adapt ("Splunk is down, use traces") | MCP `isError=true` |
| Same shape offline and live | CI and learning without the lab; contract tests catch drift | `fixtures.py` |

## Coarse vs fine tools
`get_slo_status` (coarse, opinionated: golden signals per service, burn rate) is what an on-call engineer looks at first,
and it costs one tool call instead of six PromQL queries. `promql_query` (fine, flexible) is the escape hatch. Give
agents both: coarse tools cut steps and tokens; fine tools prevent dead ends.

## The SPL guardrail
`search_logs` accepts SPL from the model. Without controls, a prompt-injected log line could make the agent run
`| delete`, `| outputlookup` (write), `| rest` (read server config) or `| sendemail` (exfiltrate). The validator:
requires an explicit allowed `index=`, rejects macros and leading generating commands, denies write/exec commands,
forces a time window and `| head N`. Defence in depth: the Splunk account should also be a read-only role.

## Check yourself
1. Why is a retry on `POST /api/payments/charge` dangerous but a retry on `GET /api/v1/query` fine?
2. The agent calls `get_slo_status` 3 times in one run. What does the TTL cache save at 200 investigations/min?
3. Name two SPL commands that would let an attacker exfiltrate data and how the validator blocks them.
