# Fin Analytics API — Data Model

This documents the shape of BigQuery dataset `fin_analytics` (7 tables,
populated by [`etl/run_pipeline.py`](../etl/run_pipeline.py) — see
[`../README.md`](../README.md) for how it's loaded) and why it's structured
this way. Scope note: this project is an API/GCP showcase, not a data-
engineering one (see `.claude/context.md`), so this is a lightweight
reference diagram, not a formal dimensional model (no fact/dim typing, no
SCD handling) — BigQuery also doesn't enforce any of the keys below; they're
join conventions followed by the ETL and the API's SQL, not constraints.

## Entity-relationship diagram

```mermaid
erDiagram
    SECURITY_MASTER ||--o{ MARKET_PRICES : "priced in"
    SECURITY_MASTER ||--o| FUNDAMENTALS : "has"
    SECURITY_MASTER ||--o| ESG_SCORES : "has"
    SECURITY_MASTER ||--o{ PORTFOLIO_HOLDINGS : "held as"
    SECURITY_MASTER ||--o{ BENCHMARK_WEIGHTS : "weighted as"
    PORTFOLIOS ||--o{ PORTFOLIO_HOLDINGS : "holds"

    SECURITY_MASTER {
        string ticker PK
        string yfinance_ticker
        string company_name
        string gics_sector
        string gics_sub_industry
        string hq_location
        string hq_state
        date date_added
        string cik
        string founded
    }
    MARKET_PRICES {
        string ticker FK
        date trade_date PK
        float open
        float high
        float low
        float close
        float volume
    }
    FUNDAMENTALS {
        string ticker "PK, FK"
        float market_cap
        float trailing_pe
        float forward_pe
        float dividend_yield
        float beta
        float fifty_two_week_high
        float fifty_two_week_low
        string currency
        string country
        int full_time_employees
        float return_on_equity
        float profit_margins
        float revenue_growth
        float debt_to_equity
    }
    ESG_SCORES {
        string ticker "PK, FK"
        string source
        float total_esg_risk_score
        float environment_risk_score
        float social_risk_score
        float governance_risk_score
        int controversy_level
        string risk_category
    }
    PORTFOLIOS {
        string portfolio_id PK
        string portfolio_name
        string strategy
        float aum_usd
        float cash_weight
        string benchmark_id
        date as_of_date
    }
    PORTFOLIO_HOLDINGS {
        string portfolio_id "PK, FK"
        string ticker "PK, FK"
        date as_of_date
        float shares
        float last_close
        float market_value
        float weight
    }
    BENCHMARK_WEIGHTS {
        string benchmark_id PK
        string ticker "PK, FK"
        date as_of_date
        float weight
    }
```

## Why this shape

`security_master` is the hub: every other table hangs off `ticker`.
`market_prices` / `fundamentals` / `esg_scores` are satellites around it —
one time series, one latest-snapshot row, and one latest-snapshot row per
ticker, respectively. That split (rather than one wide table) exists
because the three feeds have genuinely different grain and update
cadence — daily OHLCV bars vs. point-in-time company/ESG snapshots — which
mirrors how a real buy-side data org receives them as separate vendor
feeds (market data vendor, fundamentals vendor, ESG ratings provider).

`portfolios` / `portfolio_holdings` / `benchmark_weights` are the portfolio
side: `portfolio_holdings` is the bridge between `portfolios` and
`security_master` (portfolio_id + ticker → weight/shares/market_value),
and `benchmark_weights` is the same shape one level up (ticker → weight for
a given `benchmark_id`, independent of any single portfolio).

Two things worth calling out rather than glossing over:
- **No `benchmarks` dimension table.** `benchmark_id` is a plain string
  that `portfolios.benchmark_id` and `benchmark_weights.benchmark_id` both
  happen to use consistently (currently all 5 portfolios point at the same
  `BM_BROAD500`). A real model would likely promote this to its own table
  once more than one benchmark exists; skipped here since it would be a
  table with no columns beyond an ID.
- **Keys are convention, not enforcement.** BigQuery has no primary/foreign
  key constraints — joins correctness is maintained by the ETL (see
  `etl/generate_portfolios.py`'s merges) and by the API's SQL (see each
  router under `app/routers/`), not by the database.
