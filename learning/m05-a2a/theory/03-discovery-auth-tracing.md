# 3. Discovery, auth and tracing across hops

**Discovery.** The orchestrator binds to *skills*, not hosts: read cards from a registry → index
`skill → (agent, endpoint)` → refuse duplicates. Production registries: service catalog (Backstage), Kubernetes
Services + a card-serving sidecar, API gateway. Cards are cacheable; refresh on 404 / version change.

**Auth.** Cards are public; skills are not. The card advertises the scheme; the client sends credentials on every call.
Here: static bearer (`M05_TOKEN`). Production (M8/M9): OAuth2 client-credentials per caller, mTLS inside the mesh,
per-skill authorization (only the orchestrator may call `executor`), and the **agent re-checks policy itself** -
never trust that the caller already did.

**Tracing.** One W3C `traceparent` trace id per incident, a new span id per hop. The callee echoes it in artifact
metadata here; in M7 both sides create OTel spans so Jaeger shows orchestrator → 7 agents → Prometheus/Jaeger/Splunk
as one trace. Without it, a slow incident response across 11 hops is undebuggable.
