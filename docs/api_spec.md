# Fin Analytics API — Endpoint Spec

Base URL: `http://localhost:8000`. Interactive OpenAPI docs are auto-served by
FastAPI at `/docs` (Swagger UI) and `/openapi.json` (raw spec) once the app
is running — this document is the design-intent summary behind that spec.

This is a **code-first** API: the OpenAPI contract is generated from the
FastAPI routes and Pydantic models, not hand-authored up front. A snapshot
of that generated contract is committed at
[`openapi.yaml`](openapi.yaml) (regenerate with
`python scripts/export_openapi.py` after changing any route/model) so the
contract can be reviewed or diffed without running the server.

All data is served from BigQuery dataset `fin_analytics` (see
[`../README.md`](../README.md) for how it's populated, and
[`data_model.md`](data_model.md) for the table-level ER diagram/rationale).
Audience tags: **PM** = portfolio manager, **ESG** = ESG/responsible-investment
team.

## Authentication & authorization

Every endpoint except `/health` and `/health/ready` requires an
`X-API-Key` header. Keys are issued and revoked out-of-band with
[`scripts/manage_api_keys.py`](../scripts/manage_api_keys.py) (see its
module docstring) — there is no self-service signup. A missing key
returns `401`; a key that's valid but lacks the required scope returns
`403`.

Each key is granted a set of scopes, checked per-route (see
[`app/auth.py`](../app/auth.py)):

| Scope | Covers |
|---|---|
| `standard:read` | `securities/*`, `benchmarks/*`, `esg/screen` — reference/market data, nothing portfolio-specific |
| `confidential:read` | `portfolios/*` (list, holdings, exposures, performance) and the two portfolio-scoped ESG endpoints — anything that reveals a specific portfolio's real positions, weights, AUM, or returns |

`standard:write` / `confidential:write` are reserved for future
write endpoints (none exist yet — every current route is `GET`).

Granted scopes are cached in-process for 5 minutes, so revoking a key
can take up to that long to take effect on an already-warm instance.

## Rate limiting

Each API client gets a token bucket: 5 requests/s sustained, bursts of up
to 20 (`RATE_LIMIT_PER_SECOND` / `RATE_LIMIT_BURST` env vars; see
[`app/rate_limit.py`](../app/rate_limit.py)). Over the limit returns `429`
with a `Retry-After` header. Limits are tracked per Cloud Run instance, so
a client spread over several instances can exceed its nominal limit. That's
accepted here: the limiter is mainly a cost brake on BigQuery queries, not
a hard quota. `/health*` is not rate-limited.

## Request IDs & logging

Every response carries an `X-Request-ID` header, echoing the caller's own
`X-Request-ID` if it sent one. Each request writes one structured JSON log
line (method, URL, status, latency, client, request id), and each billed
BigQuery query writes another (bytes processed, slot time, duration, job
id). Both are tied to the request's Cloud Trace id, so they group under
the request in Cloud Logging. See
[`app/observability.py`](../app/observability.py).

## Response envelope & pagination

Every endpoint — singleton or collection — returns the same top-level
shape, so a client parses every response the same way regardless of
whether `data` holds one object or a list:

```json
{
  "data": <object | array>,
  "meta": {
    "pagination": {
      "next_cursor": "<opaque string>" | null,
      "limit": <int>,
      "has_more": <bool>
    } | null
  }
}
```

`meta.pagination` is `null` for singleton endpoints (e.g.
`GET /securities/{ticker}`) and populated for every list endpoint.

Pagination is **cursor-based** (keyset pagination), not offset-based: each
list endpoint accepts `cursor` and `limit` query params. `cursor` is an
opaque token — pass it back exactly as received from
`meta.pagination.next_cursor` to get the next page; omit it for the first
page. `limit` caps the page size (default 50 / max 500 on most list
endpoints; `esg-laggards` defaults to 10 / max 100, matching its "top N"
intent). `next_cursor` is `null` once `has_more` is `false`.

Cursor pagination was chosen over offset (`?page=2`) because it stays
correct even if rows are added/removed between page fetches — each page is
defined relative to the last row actually seen, not a row count that can
shift. Each endpoint sorts by a stable keyset (a unique column, or a
column plus a tiebreaker column where the primary sort value can repeat,
e.g. holdings weight + ticker) so pages never skip or repeat a row.

## Caching & overload behaviour

Query results are cached in-process per Cloud Run instance for 5 minutes,
keyed by the exact query + parameters. The warehouse is reloaded once a
day, so this is effectively never stale; right after a data load, a
response can be up to 5 minutes old.

Any data endpoint can return `503` with a `Retry-After` header if BigQuery
is rate-limiting this service (heavy load) and doesn't recover within
~10 seconds. It's transient: retry after the indicated delay.

## 1. `GET /securities/{ticker}` — Security 360 profile (PM, ESG)
Reference data + latest fundamentals + latest ESG scores + latest close in
one call — the "security profile" screen a PM or ESG analyst opens first.
- **Response**: `data` = `SecurityProfile` (sector/sub-industry, market cap,
  PE, dividend yield, beta, last close, ESG total/E/S/G risk scores, risk
  category, data source). `meta.pagination` = `null`. Fundamentals, ESG
  and price fields are `null` for tickers in the security master that have
  no data in those tables (currently 403 of the 503).
- **Errors**: 404 if ticker not in the security master.

## 2. `GET /securities/{ticker}/prices` — Historical OHLCV (PM)
Daily adjusted open/high/low/close/volume for one ticker, oldest first.
- **Query params**: `start`, `end` (ISO dates, both optional), `cursor`,
  `limit` (default 50, max 500). Keyset: `trade_date`.
- **Response**: `data` = list of `PricePoint`.
- **Errors**: 404 if no price history at all for the ticker (only checked
  on the first page, i.e. when `cursor` is omitted).

## 3. `GET /portfolios` — List portfolios (PM, ESG)
All model portfolios with strategy, AUM, cash weight, and benchmark id.
- **Query params**: `cursor`, `limit` (default 50, max 500). Keyset:
  `portfolio_id`.
- **Response**: `data` = list of `PortfolioSummary`.

## 4. `GET /portfolios/{portfolio_id}/holdings` — Current holdings (PM)
Full holdings list (ticker, sector, weight, shares, market value), the
books-and-records view of a portfolio, sorted by weight descending.
- **Query params**: `cursor`, `limit` (default 50, max 500). Keyset:
  `weight` desc, `ticker` asc (tiebreaker).
- **Response**: `data` = list of `HoldingRow`.
- **Errors**: 404 if portfolio id unknown.

## 5. `GET /portfolios/{portfolio_id}/exposures` — Sector active weight (PM)
Portfolio vs. benchmark sector weights and the active (over/underweight)
position per GICS sector — a PM's standard sector-tilt check, sorted by
active weight descending.
- **Query params**: `cursor`, `limit` (default 50, max 500). Keyset:
  `active_weight` desc, `gics_sector` asc (tiebreaker).
- **Response**: `data` = list of `SectorExposure`.

## 6. `GET /portfolios/{portfolio_id}/performance` — Return vs. benchmark (PM)
Cumulative portfolio and benchmark return over a date range, computed by
holding *today's* weights constant and compounding daily security returns.
This is a simplification (no rebalancing/weight drift is modelled) and is
labelled as such — it is not an audited performance return.
- **Query params**: `start`, `end` (ISO dates, both optional; default to
  the full available price history), `cursor`, `limit` (default 50, max
  500). Keyset: `trade_date`.
- **Response**: `data` = list of `PerformancePoint` (date, portfolio
  cumulative return, benchmark cumulative return).

## 7. `GET /portfolios/{portfolio_id}/esg-summary` — Weighted ESG profile (ESG, PM)
Portfolio's AUM-weighted total/E/S/G risk scores vs. the benchmark's
weighted total score, plus the weight distribution across risk categories
(Negligible/Low/Medium/High/Severe) — the ESG team's first portfolio check.
- **Response**: `data` = `ESGPortfolioSummary`. `meta.pagination` = `null`
  (this is a single aggregated object, not a list).

## 8. `GET /portfolios/{portfolio_id}/esg-laggards` — Top ESG risk contributors (ESG)
Holdings ranked by weight × ESG risk score, i.e. the names doing the most
damage to the portfolio's aggregate ESG profile — used to drive engagement
or exclusion conversations.
- **Query params**: `cursor`, `limit` (default 10, max 100 — "top N" is
  just this endpoint's first page). Keyset: `weighted_risk_contribution`
  desc, `ticker` asc (tiebreaker).
- **Response**: `data` = list of `ESGLaggard`.

## 9. `GET /esg/screen` — Cross-portfolio ESG/sector/size screener (ESG)
Screens the whole security universe by sector, max ESG risk score, and/or
minimum market cap — used to build exclusion or approved-list candidates
independent of any one portfolio, sorted by ESG risk ascending.
- **Query params**: `sector`, `max_risk_score`, `min_market_cap`, `cursor`,
  `limit` (default 50, max 500). Keyset: `total_esg_risk_score` asc,
  `ticker` asc (tiebreaker).
- **Response**: `data` = list of `ScreenResult`.

## 10. `GET /benchmarks/{benchmark_id}/constituents` — Benchmark weights (PM)
Full constituent list and weights for a benchmark, for the same
sector/weight comparisons `exposures` does, at the raw constituent level,
sorted by weight descending.
- **Query params**: `cursor`, `limit` (default 50, max 500). Keyset:
  `weight` desc, `ticker` asc (tiebreaker).
- **Response**: `data` = list of `BenchmarkConstituent`.
- **Errors**: 404 if benchmark id unknown (checked on the first page only).

---

## Cross-cutting notes
- `GET /health` and `GET /health/ready` are the exceptions to the envelope
  — both return a bare `{"status": "ok"}` rather than
  `{"data": ..., "meta": ...}`, matching the plain-body convention most
  uptime/monitoring tooling (incl. Cloud Run's own health probing) expects.
  `/health` is a pure liveness check (process is up, no dependencies
  touched); `/health/ready` additionally runs a trivial BigQuery query and
  returns `503` if the warehouse is unreachable, so dashboards that need to
  know "can this API actually serve data" should poll that one instead.
- An invalid/malformed `cursor` returns `400 {"detail": "invalid cursor"}`.
- Dates are ISO `YYYY-MM-DD`. All weights are fractions (0–1), not
  percentages.
- `esg_source` on `SecurityProfile` / underlying `esg_scores` rows is either
  `yahoo_sustainalytics` (real vendor-sourced data) or `synthetic_fallback`
  (deterministic, sector-tilted synthetic score used when the free vendor
  feed has no coverage for that ticker) — ESG consumers should filter or
  flag on this before using scores for real decisions.
