# ShopSphere Observability Lab

A small but realistic production system that every agent in the program (M2–M12) observes, diagnoses and operates.

```
             Locust (loadgen :8089)
                     │  HTTP
                     ▼
  Browser ──► ShopSphere shop API (:8080) ──HTTP──► payments service
              │  auth · catalog · search · cart     │  (same image, SERVICE_ROLE=payments)
              │  checkout · orders · chaos API      │
              ├─► Postgres (products, orders)       │
              └─► Redis (sessions, cart, cache, chaos flags)
                     │ OTLP (traces · metrics · logs)
                     ▼
            OpenTelemetry Collector (:4317/:4318)
       ┌─────────────┼───────────────────────┐
       ▼             ▼                       ▼
   Jaeger (APM)   Prometheus (:9090)      Splunk (HEC :8088, Web :8000)
   (:16686)       SLO rules + alerts        logs with trace_id
       └──────────► Grafana (:3000) ◄────────┘
```

## Run it (Windows Docker Desktop, 16 GB RAM)

Give Docker Desktop at least **8 GB** of RAM (Settings → Resources). Splunk uses about 2–3 GB of it.

```powershell
cd lab
copy .env.example .env      # optional: change lab passwords
docker compose up -d --build
docker compose ps           # wait until everything is Up or healthy (Splunk takes about 2 min)
```

To skip Splunk on a smaller machine, run `docker compose up -d --scale splunk=0`.

| UI | URL | Login |
|---|---|---|
| ShopSphere web app | http://localhost:8080 | alice / shopsphere |
| ShopSphere API docs (OpenAPI) | http://localhost:8080/docs | - |
| Grafana (SLO dashboard) | http://localhost:3000 | admin / admin |
| Jaeger (APM, traces, Monitor tab) | http://localhost:16686 | - |
| Prometheus (rules, alerts) | http://localhost:9090/alerts | - |
| Splunk (logs) | http://localhost:8000 | admin / ShopSphere#Lab1 |
| Locust (load) | http://localhost:8089 | - |

Any username works in the app as long as the password is `shopsphere`.

## Signals you get

- **Traces.** Auto-instrumented FastAPI, asyncpg, Redis and httpx, plus business spans (`checkout.price_and_reserve`, `payment-provider.authorize`). Context propagates shop → payments in one trace.
- **Metrics.**
  - OTel semconv `http_server_request_duration_seconds`, `http_client_request_duration_seconds` and `http_server_active_requests`.
  - Business metrics `shop_orders_total{result}`, `shop_payments_total{result}` and `shop_order_value_USD`.
  - Span RED metrics `traces_span_metrics_*` from the collector's spanmetrics connector.
- **Logs.** JSON stdout and OTLP logs with `trace_id`/`span_id`, sent to Splunk `index=main sourcetype=shopsphere:otel`.
- **SLOs.** See `prometheus/rules/slo.yml`.
  - Availability is 99.5%, with multi-window, multi-burn-rate alerts (14.4x fast burn, 6x slow burn).
  - Checkout latency target: 95% of requests under 1s.

## Break it (chaos)

```bash
curl -X POST localhost:8080/api/chaos/scenarios/payments-flaky    # 35% payment errors + latency
curl -X POST localhost:8080/api/chaos/scenarios/checkout-latency  # +800ms ±400ms on checkout
curl -X POST localhost:8080/api/chaos/scenarios/slow-db           # 250ms on every DB query
curl -X POST localhost:8080/api/chaos/scenarios/payments-outage   # payments returns 503
curl -X POST localhost:8080/api/chaos/scenarios/cpu-spike         # CPU burn per request
curl -X POST localhost:8080/api/chaos/scenarios/error-storm       # 20% 5xx on the shop API
curl -X POST localhost:8080/api/chaos/scenarios/search-degraded   # slow, erroring search
curl -X POST localhost:8080/api/chaos/scenarios/reset
curl -X PUT  localhost:8080/api/chaos/shop -H 'content-type: application/json' \
     -d '{"latency_ms":300,"error_rate":0.05,"routes":["/api/search"]}'   # custom fault
```

You can also use the **Chaos** panel in the web UI. Scale the load with `LOAD_USERS=200 docker compose up -d loadgen` or from the Locust UI.

## Practice drills (do these before M2)

1. Apply `payments-flaky`. Find the alert in Prometheus, the failing span in Jaeger, and the matching log in Splunk by `trace_id`. Time how long that takes you: that is your manual MTTR baseline the agents must beat.
2. Apply `slow-db`. Which golden signal moves first? Why does checkout p99 grow more than catalog p99?
3. Run `LOAD_USERS=200` and find the saturation point, where p95 bends. Use Little's Law to explain it with the M1 `capacity_calculator`.
4. Write a Splunk query (SPL) that returns error logs with their trace ids:
   `index=main sourcetype=shopsphere:otel otel.log.severity.text=ERROR | table _time service.name _raw trace_id`

The runbooks the agents will retrieve in M2/M3 are in [docs/runbooks.md](docs/runbooks.md).

## Ports used

8080 · 3000 · 9090 · 16686 · 8000 · 8088 · 8089 · 8090 · 4317 · 4318. Change the left-hand side of `ports:` in `docker-compose.yml` if any of these clash.
