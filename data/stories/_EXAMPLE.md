<!--
ILLUSTRATIVE EXAMPLE ONLY — fictional, do NOT cite this in real applications.
Underscore-prefixed so the indexing loader skips it (same rule as _TEMPLATE.md).
Use it to see the LEVEL OF CONCRETENESS expected, then write your OWN real stories
in files WITHOUT a leading underscore (e.g. order-service-latency.md).
-->

# Title: Cut order-service p99 latency 70% under Black-Friday load

**Role / Context:** Senior Software Engineer, Checkout team, a mid-size e-commerce company, 2023–2024.
**Tech:** C#, .NET 8, ASP.NET Core, Azure (App Service, Service Bus, Redis), SQL Server, Application Insights.

## Situation
Our order-placement API degraded badly under peak load — p99 latency hit ~4s during flash sales and we shed ~3% of carts to timeouts. A Black-Friday event was 6 weeks out and projected 5x normal traffic.

## Task
I owned the checkout write-path. Goal: keep p99 under 800ms at 5x traffic without a full rewrite, and do it without losing the at-least-once order guarantee finance depended on.

## Action
I profiled with Application Insights and found two hotspots: a synchronous call to the inventory service inside the request path, and lock contention on a per-SKU SQL row. I (1) moved inventory reservation off the hot path onto an Azure Service Bus queue with an idempotent consumer keyed on order id; (2) added a Redis read-through cache for hot SKU availability with a short TTL; (3) replaced the pessimistic SQL lock with optimistic concurrency (rowversion) + retry. I weighed eventual consistency on stock counts against latency, and chose to over-reserve slightly and reconcile, since overselling was the only truly unacceptable outcome.

## Result
p99 dropped from ~4s to ~1.1s in load tests, ~0.7s after the Redis tuning — a ~70-80% cut. Cart-timeout drop-off fell from 3% to under 0.4%. Black-Friday ran with zero checkout incidents at 5.2x baseline. Biggest lesson: most "scaling" wins came from removing a synchronous dependency, not from adding hardware.

## Skills demonstrated
C#, .NET 8, ASP.NET Core, Azure Service Bus, Redis, SQL Server concurrency, performance profiling, distributed systems, eventual consistency tradeoffs, idempotency, ownership
