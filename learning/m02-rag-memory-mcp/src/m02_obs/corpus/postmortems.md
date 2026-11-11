---
type: postmortem
---
# ShopSphere postmortems

## pm-2026-09-payments-latency
**Impact:** 38 minutes, 31% of checkouts slower than 1s, checkout latency SLO alert paged. No errors.
**Root cause:** the payment provider degraded; `payment-provider.authorize` p95 rose from 40ms to 1.9s. The shop's
checkout latency tracked payments latency one-to-one. The team first scaled shop replicas, which did not help because
the shop was not saturated.
**What worked:** comparing the checkout trace's `checkout.price_and_reserve` span (fast) with the payments span (slow)
in Jaeger. **Action items:** add a payments circuit breaker; degrade gracefully ("payment pending") instead of holding
the request; alert on payments p95 directly.

## pm-2026-10-db-pool-exhaustion
**Impact:** 22 minutes, p99 for catalog and checkout above 2s, `ShopSphereHighP99` fired.
**Root cause:** a config change reduced `DB_POOL` from 20 to 4; requests queued waiting for connections. Little's Law:
40 rps × 0.12s = 4.8 connections in use at steady state, more than the pool.
**What worked:** Grafana in-flight requests rising while CPU stayed flat pointed at a queue, not compute.
**Action items:** alert on pool wait time; validate pool size against peak concurrency in CI.

## pm-2026-10-payments-outage
**Impact:** 12 minutes of failed checkouts (`shop_orders_total{result="payment_failed"}`), error budget fast burn.
**Root cause:** payments-service returned 503 for every charge after a bad deploy.
**What worked:** the error-budget-burn runbook; rollback restored service within 4 minutes of diagnosis.
**Action items:** canary deploys for payments; keep carts on payment failure so users can retry.
