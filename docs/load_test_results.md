# Load test results: pass 8 vs pass 10

How the API's tail latency and throughput improved under load, measured
against the live Cloud Run deployment.

## Test setup

- **Target**: Cloud Run service in `europe-west4` (1 vCPU / 512 MiB per
  instance, concurrency 40, max 10 instances), BigQuery dataset in the same
  region.
- **Load**: [Locust](../loadtest/locustfile.py), 150 concurrent users,
  ramped up over 10 seconds, 2-minute run, weighted mix across all 10
  endpoints plus `/health`.
- **Pass 8**: after switching to single-call `jobs.query` execution, before
  result caching and fail-fast retries.
- **Pass 10**: with result caching and fail-fast retries, run in a mode
  where nearly every request uses random parameters (`limit`, date ranges,
  ESG threshold). Most queries are therefore unique and miss the cache, so
  BigQuery gets the same load as in pass 8.

## Results

| | Pass 8 (no cache, no fail-fast) | **Pass 10 (cache misses, fail-fast)** |
|---|---|---|
| BigQuery query calls | 11,847 | **12,456** (caching wasn't helping, as intended) |
| BigQuery 403s (rate-limited) | 1,036 | **1,002** (same pressure) |
| median / p95 | 220ms / 1.5s | **160ms / 330ms** |
| p98 / p99 | 2.7s / 34s | **510ms / 2.6s** |
| slowest request, Cloud Run's own measurement | ~57s | **17s** |
| throughput | 88 req/s | **166 req/s** |
| failures | 0 | **25 (0.13%), all 503** |

## What the numbers show

- **The comparison is fair.** In pass 10, BigQuery got slightly more
  queries than in pass 8 and rejected about as many calls for rate
  limiting. The improvement comes from how the API handles that pressure,
  not from less load.
- **Most rate-limited calls still succeed.** About 1,000 BigQuery calls were
  rejected, and nearly all succeeded on a retry within a 10-second budget.
  Only 25 requests used up the budget.
- **Failures are fast and retryable.** Those 25 requests returned
  `503 Service Unavailable` with a `Retry-After` header after 9–12 seconds.
  Before fail-fast, the BigQuery client kept retrying silently for minutes,
  so the same requests hung for 30–120 seconds and held server threads
  while they waited. All 25 came from one rate-limit spike about 80 seconds
  into the test.
- **The slowest successful requests (15–17s) came from that same spike.**
  Some endpoints run two queries, each with its own retry budget, and
  requests queued while that instance's threads waited between retries.
- **Caching still helps when most queries are unique.** Endpoints without
  varying parameters (the security profile, the portfolio lookup that
  several endpoints run first) stayed cached. About the same number of
  BigQuery calls served 1.9x as many requests: 166 vs 88 per second.
- **Slowest request is measured server-side.** Locust's own maximum was
  higher, but those outliers came from the local `gcloud run services
  proxy` relaying about 200 requests per second from a laptop. Cloud Run's
  logs never saw them as slow.

## What changed between the two passes

1. **Result cache**: each distinct query (SQL plus parameter values) is
   kept in memory per instance for 5 minutes. The warehouse is reloaded
   once a day, so cached results are effectively never stale.
2. **Fail-fast retries**: BigQuery's client retries are capped at 10
   seconds. An overloaded request returns a 503 with `Retry-After` instead
   of hanging.

The earlier fix, already in place for pass 8, was single-call query
execution (`query_and_wait` with `JOB_CREATION_OPTIONAL`). It cut BigQuery
API calls from 3 to 1 per query.

## Remaining limit

BigQuery accepts roughly 100 API requests per second from one caller
identity, and every instance of this service shares one identity. That
caps how many *unique* queries per second the API can serve. Repeated
queries are served from the cache and aren't limited by it. If real
traffic approached that ceiling, the next steps would be precomputing hot
results or moving the serving path to a database built for request
serving.

## Post rate-limiting validation (2026-11-11)

After adding per-client rate limiting (5 req/s, burst 20, per instance) and
fixing two bugs found while verifying it (a 500 on tickers missing
fundamentals/ESG/price data, and missing `X-Request-ID` on 500s), ran two
final passes against the then-current revision
(`fin-analytics-api-00017-9lh`) with one load-test API key.

**Pass A — realistic single-client load** (3 users, ~1.5 min, repetitive
params, ~3.8 req/s, under the rate limit): 242 requests, **0 failures**.
Median 27ms, p95 220ms, p98 330ms. A handful of requests up to ~8s coincided
with a single cold-start event (multiple endpoints, including `/health`,
spiked together) — not a BigQuery or rate-limiting issue.

**Pass B — deliberate 150-user burst**, same single API key, same mix: of
25,319 requests, 21,673 got a `429 rate limit exceeded` (clean, with
`Retry-After`) and 3,737 succeeded — **zero 503s, zero other errors**.
Locust itself reported response times up to 47.7s, but cross-checking Cloud
Run's own server-side request logs (`httpRequest.latency`, which Cloud Run
promotes to a top-level `LogEntry` field — confirms the assumption noted in
`terraform/observability.tf`) for the full test window showed a **true
max of 178ms** across all 25,410 server-side log entries. The Locust-side
outliers are the same client/local-proxy artifact documented for pass 9/10
above (150 concurrent connections through a laptop-run `gcloud run services
proxy`), not a server regression.

**Conclusion**: the rate limiter does exactly what it's designed to do —
protect the service (and the BigQuery budget) from a single noisy or
misbehaving client without ever reintroducing the old retry-storm tail
latency, even at 150 concurrent users on one API key. `/health` is
confirmed never rate-limited (served all requests in both passes).

## Multi-client aggregate validation (2026-11-12)

Pass A/B above used one shared API key, so they only proved the limiter
protects against a single noisy client — they left open whether many
*legitimate* concurrent clients would behave differently in aggregate. This
pass closes that gap.

- Issued 40 separate API keys (`loadtest-multi-01..40`), each its own
  `client_name` and therefore its own rate-limit bucket.
  `loadtest/locustfile.py` gained `LOAD_TEST_API_KEYS` (comma-separated)
  support: simulated users round-robin across the list at spawn time instead
  of all sharing one key.
- 120 simulated users (3 per key on average), 2 minutes,
  `LOAD_TEST_VARY_PARAMS=1` (randomised params — the more realistic,
  mostly-cache-miss setting), against revision `fin-analytics-api-00017-9lh`.
- **Locust-reported**: 17,466 requests, **0 failures**, 147 req/s. p50 160ms,
  p95 390ms, p98 520ms, p99 850ms, one 25.5s outlier.
- **Cross-checked against Cloud Run's own server-side request logs** (same
  method as every pass above — the laptop-run `gcloud run services proxy`
  tunnel inflates Locust's own timing): all 17,595 server-side log lines
  were `200` — zero 429s, zero 5xx. True server-side latency: p50 120ms,
  p95 287ms, p98 380ms, p99 466ms, p99.9 1.1s, **true max 2.1s** — the 25.5s
  Locust outlier was the same proxy artifact, not a real stall. The 10
  slowest requests all land within the same ~150ms window, i.e. one brief
  scaling blip at ramp-up, not sustained slowness.
- 41 distinct `client_name` values appear in the logs: the 40 real keys
  plus `None` (`/health`, which is unauthenticated and never gets a
  `client_name`). Every real client got at least one successful response —
  none was starved while others sailed through.
- **BigQuery load check** (Cloud Monitoring, `consumed_api` /
  `bigquery.googleapis.com`): real BigQuery API call rate peaked at ~83
  req/s during the busiest minute, with zero `403 rateLimitExceeded`
  responses — close to, but safely under, the ~100 req/s-per-identity
  ceiling found on 2026-11-10. So this result wasn't "nowhere near the
  limit" — the backend was genuinely operating near the known ceiling
  without tripping it, which is the honest way to state the capacity
  number below.
- One unrelated, transient event during the warm-up sanity check *before*
  this pass (not counted in the numbers above): a single Cloud Run
  platform-level 500 ("aborted after waiting too long for an available
  instance") during a sharp 4-second ramp to 40 users — a cold-start/
  autoscaling artifact, not an application bug (same class of issue the
  original tail-latency investigation solved by preferring gentler ramps).
  It did not recur in the full 2-minute run.

**Conclusion**: the open caveat from Pass A/B is now closed. 40 independent,
legitimate clients can transact concurrently, each safely inside its own
rate-limit budget, with no false 429s and no 5xx, server-side p99 under
500ms, while real BigQuery traffic ran close to its known ~100 req/s
ceiling. No bugs found.

**Headline capacity numbers (server-side, this pass)**: ~150 req/s aggregate
sustained throughput across many clients, p95 < 290ms, p98 < 380ms,
p99 < 470ms, p99.9 < 1.1s.
