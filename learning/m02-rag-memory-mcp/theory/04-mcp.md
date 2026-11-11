# 04 · Model Context Protocol (MCP)

MCP standardises how an AI application gets tools and context. Write the observability integration **once** as an
MCP server; every host (this agent, Claude Desktop, Claude Code, Cursor, the M4 multi-agent system) can use it.

```
Host (the AI app: m02 investigator, Claude Desktop)
 └─ Client (one per server connection, JSON-RPC 2.0)
     └─ Server (observability-mcp-server)
          ├─ tools      get_slo_status, list_firing_alerts, promql_query, search_traces, get_trace,
          │             search_logs, get_recent_changes, search_runbooks   (model-controlled actions)
          ├─ resources  runbook://{chunk_id}, kb://index                    (app-controlled context)
          └─ prompts    investigate(symptom)                                (user-controlled templates)
```

## Lifecycle
`initialize` (version + capabilities negotiation) → `tools/list` → `tools/call` … Tool results carry `content` (text for
the model), optional `structuredContent` (typed JSON matching an `outputSchema`) and `isError`. A tool failure is a
*result* with `isError: true`, not a protocol error, so the model can read it and adapt.

## Transports
| Transport | Use | Notes |
|---|---|---|
| stdio | local: host spawns the server as a subprocess | no network exposure; credentials via env |
| Streamable HTTP | remote/shared server, `POST /mcp` (+ optional SSE stream) | needs auth (OAuth 2.1 / bearer), TLS, rate limits |
| SSE (legacy) | older hosts | superseded by Streamable HTTP |

## Tool annotations
`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` tell the host how risky a tool is (e.g. auto-approve
read-only tools, ask a human for destructive ones). They are **hints from the server**, not enforcement: the server
still validates (SPL guardrail), and the host still decides policy.

## Security checklist for an enterprise MCP server
Least-privilege backend credentials (read-only Splunk role) · authN/authZ per caller on HTTP transport · input
validation on every argument · output size caps · audit log of every call (who, tool, args, latency, result size) ·
no secrets in tool results · pin and review third-party MCP servers (a malicious tool description is prompt injection).

## Check yourself
1. Why is a runbook a *resource* and `search_runbooks` a *tool*?
2. You expose the server over HTTP to 30 teams. List four controls you add that stdio did not need.
