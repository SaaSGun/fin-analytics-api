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
