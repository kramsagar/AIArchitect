---
type: architecture
---
# ShopSphere architecture

## service-map
`shopsphere-shop` (FastAPI, port 8080) serves the UI and REST API: auth, catalog, search, cart, checkout, orders.
It depends on Postgres (catalog, orders, stock), Redis (sessions, carts, catalog cache, chaos config) and
`payments-service` over HTTP (`POST /api/payments/charge`). `payments-service` calls an external payment provider,
modelled by the `payment-provider.authorize` span. Checkout is the only route on the critical revenue path.

## checkout-flow
`POST /api/checkout`: load cart from Redis → `checkout.price_and_reserve` (Postgres transaction: price lookup and
stock reservation) → call payments with a `PAYMENT_TIMEOUT_S` budget (default 2s) → insert order → clear cart.
If payments fails or times out, stock is released and the order is recorded with `result=payment_failed`.

## dependency-budgets
Latency budget for checkout p95 < 1s: Redis ≤ 5ms, Postgres transaction ≤ 50ms, payments ≤ 700ms, app overhead ≤ 100ms.
Timeouts must be smaller than the caller's budget. Retries to payments are NOT automatic: a charge is not idempotent
without an idempotency key, so a blind retry can double-charge.

## telemetry
All services export OTLP to the collector. Traces → Jaeger, metrics → Prometheus (http_server_request_duration_seconds,
shop_orders_total, shop_payments_total, span metrics), logs → Splunk index=main sourcetype=shopsphere:otel with
`trace_id`, `span_id`, `service.name` and `otel.log.severity.text` fields.
