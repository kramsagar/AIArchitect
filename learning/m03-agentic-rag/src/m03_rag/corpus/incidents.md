---
type: incident
---
# ShopSphere incident reports (raw, written during the incident)

## inc-4127-purchase-flow-sluggish
Customers say the purchase flow is sluggish and the "place order" button spins. Order completion time is up to 2s.
The storefront pods are idle (CPU 20%). The time is spent waiting on the card processor (`payments-service`).
Workaround: enabled `PAYMENTS_TIMEOUT_MS=800` with a "payment pending" message. Resolved when the provider recovered.

## inc-4188-pg-53300
Error code `PG-53300 too_many_connections` in shop logs right after deploy v2.31.0. Checkout returned 500s and the
error budget burned at 16x. Cause: the connection pool was raised to 200 per pod x 24 pods, above Postgres
`max_connections=500`. Fix: roll back, then set the pool to 15 per pod and put PgBouncer in front of Postgres.

## inc-4203-pay-503-upstream
Error code `PAY-503-UPSTREAM` from the payments service; orders fail with 502 at the shop. The payment provider
rejected all calls for 12 minutes. The shop kept retrying charges, which created duplicate authorisations.
Lesson: never retry a non-idempotent charge without an idempotency key; open the circuit breaker instead.

## inc-4251-redis-evictions
Cart contents disappear randomly. Redis `evicted_keys` climbed because `maxmemory` was 64mb and sessions have a 1h TTL.
Search results also became slower because the catalog cache was evicted. Fix: raise maxmemory to 512mb, use
`allkeys-lru` only for cache keys and a separate Redis database for sessions.
