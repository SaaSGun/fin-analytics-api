# Fin Analytics API

A demo investment-management analytics API: BigQuery warehouse + FastAPI
service, deployed on Cloud Run, modelled on the kind of data a buy-side
data engineering team assembles from vendor feeds (index/reference data,
market data, ESG ratings) and internal systems (portfolio accounting), for
downstream PM and ESG consumption.

**Portfolio-project framing**: this exists to showcase GCP (BigQuery +
Cloud Run), Python, FastAPI, and API design/development skills — not data
engineering. The data below is a mix of real public sources and synthetic
data, but that distinction doesn't matter for the project's purpose: the
premise is a data-engineering teammate already produced clean data in
BigQuery, and this project picks up from there.

## Data

| Table | Grain | Source | Nature |
|---|---|---|---|
| `security_master` | 1 row / ticker | Wikipedia "List of S&P 500 companies" | real |
| `market_prices` | 1 row / ticker / day | Yahoo Finance (`yfinance`), 2y daily OHLCV | real |
| `fundamentals` | 1 row / ticker | Yahoo Finance `Ticker.get_info()` snapshot | real |
| `esg_scores` | 1 row / ticker | Yahoo Finance Sustainalytics-sourced ESG risk scores, with a sector-tilted synthetic fallback where vendor coverage is missing (flagged via `source`) — **as of this build, Yahoo's free ESG endpoint 404s for every ticker, so `source` is `synthetic_fallback` for 100% of rows**; the vendor path is left in place in case Yahoo's coverage returns | synthetic (vendor path currently dead) |
| `portfolios` | 1 row / fund | generated | synthetic ("house" model portfolios: Core Equity, ESG Leaders, Growth, Value, Dividend Income) |
| `portfolio_holdings` | 1 row / fund / ticker | generated from real fundamentals/ESG factor tilts | synthetic |
| `benchmark_weights` | 1 row / ticker | generated (market-cap weighted over the ingested universe) | synthetic |

Real position-level holdings are proprietary to a firm's PMS, so there's no
OSS dataset for that layer — `generate_portfolios.py` builds plausible model
portfolios on top of the real security/fundamentals/ESG data instead.

See [`docs/data_model.md`](docs/data_model.md) for the ER diagram and the
rationale behind this table shape.

## Setup

GCP project `fin-analytics-api` (org `saurabhgunecha-org`) already has
billing linked and the BigQuery API enabled. Python env:

```
C:\apps\anaconda\fin_api\python.exe   # conda env "fin_api"; created under C:\apps\anaconda
                                       # because venvs/conda envs under the user profile or
                                       # OneDrive path are blocked by this machine's group policy
```

## Running the pipeline

```
C:\apps\anaconda\fin_api\python.exe etl\run_pipeline.py 100
```

`100` = number of S&P 500 tickers to pull (full universe is 503; omit for
the default of 100, pass `0` to `fetch_market_data.py`/`fetch_fundamentals.py`/
`fetch_esg_scores.py` directly for all 503 — slower, one HTTP call per
ticker for fundamentals/ESG). Steps, runnable individually from `etl/`:

1. `fetch_security_master.py` — scrape + clean the S&P 500 constituent list
2. `fetch_market_data.py --limit N --period 2y` — daily OHLCV
3. `fetch_fundamentals.py --limit N` — valuation/risk snapshot
4. `fetch_esg_scores.py --limit N` — ESG risk scores (vendor + synthetic fallback)
5. `generate_portfolios.py` — synthetic model portfolios/holdings/benchmark
6. `load_bigquery.py` — loads all `data/processed/*.parquet` into BigQuery,
   `WRITE_TRUNCATE` per table

## Running the API

```
C:\apps\anaconda\fin_api\python.exe -m uvicorn main:app --reload
```

Then open `http://localhost:8000/docs` for interactive Swagger UI, or see
[`docs/api_spec.md`](docs/api_spec.md) for the endpoint-by-endpoint design
spec (10 endpoints across security profiles, portfolio holdings/exposure/
performance, and ESG summary/screening — tagged by which are aimed at
portfolio managers vs. the ESG team).

The API is code-first (contract generated from the FastAPI routes, not
hand-written up front); a committed snapshot of that generated OpenAPI
contract lives at [`docs/openapi.yaml`](docs/openapi.yaml) — regenerate it
after any route/model change with:

```
PYTHONPATH=. python scripts/export_openapi.py
```

## Running tests

```
C:\apps\anaconda\fin_api\python.exe -m pip install -r requirements-dev.txt
C:\apps\anaconda\fin_api\python.exe -m pytest
```

`tests/` is a pytest suite (`conftest.py` + one file per router/module)
covering auth scope checks, cursor pagination edge cases, and every
endpoint's success/404/403 paths. No live GCP credentials or network
access are needed — BigQuery calls (`run_query`, `get_portfolio_meta`,
the API-key cache) are monkeypatched per test, so the suite runs fully
offline against canned pandas `DataFrame`s.

Lint with `C:\apps\anaconda\fin_api\python.exe -m ruff check .` (config in
`ruff.toml`).

## CI/CD

GitHub Actions ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs
ruff + pytest on every push and PR, and deploys to Cloud Run on pushes to
`main` only after both pass. GCP auth is keyless (Workload Identity
Federation, no stored service-account key). Details and one-time setup:
[`docs/ci_cd.md`](docs/ci_cd.md).

## Deployment (Cloud Run)

Live at `https://fin-analytics-api-1089997989086.europe-west4.run.app`,
running as the least-privilege service account
`fin-api-run@fin-analytics-api.iam.gserviceaccount.com`
(`roles/bigquery.dataViewer` + `roles/bigquery.jobUser` — read-only, no
write access). The service currently **requires authentication** (no
`allUsers` invoker binding), so calling it needs an identity token or an
authenticated tunnel:

There are two independent auth layers: Cloud Run IAM below gates whether
you can reach the service at all (all-or-nothing per caller); once past
that, every route except `/health*` also requires an `X-API-Key` header
scoped to `standard:read` and/or `confidential:read` — see
[`docs/api_spec.md`](docs/api_spec.md#authentication--authorization) and
[`scripts/manage_api_keys.py`](scripts/manage_api_keys.py) for issuing
keys. The deployed service account needs no extra IAM role for this —
it only ever `SELECT`s the `api_keys` table, already covered by its
existing `bigquery.dataViewer` role.

```
gcloud run services proxy fin-analytics-api --region europe-west4 --project fin-analytics-api
```

To make it public later (e.g. to share as a portfolio link):

```
gcloud run services add-iam-policy-binding fin-analytics-api \
  --region europe-west4 --project fin-analytics-api \
  --member=allUsers --role=roles/run.invoker
```

To redeploy after a code change:

```
gcloud run deploy fin-analytics-api --source . --region europe-west4 \
  --project fin-analytics-api \
  --service-account fin-api-run@fin-analytics-api.iam.gserviceaccount.com \
  --set-env-vars="^@^GCP_PROJECT_ID=fin-analytics-api@BQ_DATASET=fin_analytics@BQ_LOCATION=europe-west4"
```

Note the `^@^`-delimited form of `--set-env-vars`: on this machine, passing a
plain comma-separated `KEY=VAL,KEY=VAL` value through PowerShell caused
`gcloud` to merge all three pairs into a single mangled env var instead of
splitting on the commas. The `^@^...@...` syntax tells `gcloud` to use `@` as
the pair delimiter instead, which avoids it — use this form for any future
`--set-env-vars`/`--update-env-vars` call from PowerShell.

This builds the `Dockerfile` via Cloud Build and pushes to Artifact
Registry automatically — no local Docker required. The image only bundles
`app/` + `main.py` (see `.dockerignore`) and installs
`requirements-app.txt`, a runtime-only subset of `requirements.txt` (the
ETL-only deps like `yfinance`/`lxml`/`beautifulsoup4` aren't needed to
serve the API).
