---
type: policy
---
# ShopSphere SLO policy

## availability-slo
Availability SLO: 99.5% of requests succeed (non-5xx) over 30 days, error budget 0.5% ≈ 3.6 hours/30d.
Fast burn: burn rate > 14.4 over 1h and 5m (2% of the monthly budget in one hour) pages. Slow burn: > 6 over 6h
and 30m opens a ticket.

## latency-slo
Checkout latency SLO: 95% of checkouts complete in under 1s. Fires `ShopSphereCheckoutLatencySLO` when more than 5% of
checkouts over 5 minutes exceed 1s.

## error-budget-policy
If more than 50% of the monthly budget is spent, feature releases to the affected service freeze until it recovers.
During an incident, mitigation (rollback, disable feature, shed load) comes before root cause analysis.
