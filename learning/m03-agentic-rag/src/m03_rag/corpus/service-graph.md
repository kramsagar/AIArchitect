---
type: architecture
---
# ShopSphere service dependency graph

## dependencies
Each line is `caller -> callee (call type, budget)`. GraphRAG uses this list to answer "what is affected if X fails?".
- edge-proxy -> shopsphere-shop (http, 1000ms)
- shopsphere-shop -> postgres (sql, 50ms)
- shopsphere-shop -> redis (cache and sessions, 5ms)
- shopsphere-shop -> payments-service (http, 800ms)
- payments-service -> payment-provider (external http, 700ms)
- payments-service -> redis (idempotency keys, 5ms)
- loadgen -> edge-proxy (synthetic traffic)

## ownership
- shopsphere-shop: team storefront, on-call rotation `storefront-oncall`, runbooks#checkout-latency
- payments-service: team payments, on-call rotation `payments-oncall`, runbooks#payments-down
- postgres: team data-platform, on-call rotation `dba-oncall`, postmortems#pm-2026-10-db-pool-exhaustion
- redis: team data-platform, on-call rotation `dba-oncall`
