# ShopSphere Runbooks

These are the RAG corpus seed for M2/M3. Every alert annotation links to a section here.

## error-budget-burn
**Signal:** `ShopSphereErrorBudgetFastBurn` / `SlowBurn`. The 5xx ratio is above 14.4x or 6x the 0.5% budget.
1. Grafana → *Error ratio by service* and *Traffic by route*. Is the burn on one route or all of them?
2. Jaeger → service `shopsphere-shop`, tag `error=true`. Find the first failing span (DB, Redis or payments).
3. Splunk: `index=main sourcetype=shopsphere:otel severity_text=ERROR | stats count by service.name, body`.
4. Check `GET /api/chaos` and recent deploys. If chaos is active in the lab, it is the "change" that caused this.
5. Mitigate first: roll back, shed load, or disable the feature. Find the root cause afterwards.

## checkout-latency
**Signal:** `ShopSphereCheckoutLatencySLO`. More than 5% of checkouts are slower than 1s.
1. Compare *Outbound call p95 (shop → payments)* with checkout p95. If they move together, the problem is the payment dependency.
2. Jaeger: open a slow checkout trace and compare `checkout.price_and_reserve` (DB) with `payment-provider.authorize`.
3. DB slow? Check the pool size (`DB_POOL`) and slow queries. Payments slow? The timeout is `PAYMENT_TIMEOUT_S` (default 2s).
4. Do not raise timeouts during an incident. That increases concurrency (Little's Law) and makes a cascading failure more likely.

## payments-down
**Signal:** `ShopSpherePaymentsErrors`. Payment declines or errors are high, and `shop_orders_total{result="payment_*"}` is rising.
1. `shop_payments_total{result}`: are these business declines or errors (503/timeout)?
2. If payments returns 503, the dependency is down. Fail fast (circuit breaker), show users a "try again" message, and keep carts.
3. Lab: `POST /api/chaos/scenarios/reset` once the cause is confirmed.

## high-latency
**Signal:** `ShopSphereHighP99`.
1. Check saturation: `http_server_active_requests`, CPU (cpu-spike chaos) and DB pool waits.
2. If the cache hit rate is low after a Redis flush, expect higher catalog and search latency until the cache warms up.
3. Scale replicas only when saturation is the cause. Adding replicas does not fix a slow dependency.
