"""
Synthetic portfolio & holdings generation.

Real position-level holdings are proprietary to a firm's portfolio
accounting system (e.g. derived from a PMS like Aladdin/Eagle/Charles River),
so there is no OSS dataset to pull here. This script instead builds
realistic-looking "house" model portfolios on top of the real security
master / fundamentals / ESG data already ingested, using simple factor
tilts (value, growth, dividend, ESG) so the resulting holdings, weights and
benchmark-relative positioning are plausible for a PM/ESG analytics API to
serve. All figures here are synthetic and for demo purposes only.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
AS_OF = date.today()

PORTFOLIOS = [
    {
        "portfolio_id": "CORE_EQ",
        "portfolio_name": "Core Equity Fund",
        "strategy": "Core / diversified large-cap",
        "aum_usd": 1_800_000_000,
        "n_holdings": 40,
        "select": "core",
    },
    {
        "portfolio_id": "ESG_LEAD",
        "portfolio_name": "ESG Leaders Fund",
        "strategy": "ESG best-in-class tilt",
        "aum_usd": 650_000_000,
        "n_holdings": 30,
        "select": "esg",
    },
    {
        "portfolio_id": "GROWTH",
        "portfolio_name": "Growth Equity Fund",
        "strategy": "Growth factor tilt",
        "aum_usd": 900_000_000,
        "n_holdings": 30,
        "select": "growth",
    },
    {
        "portfolio_id": "VALUE",
        "portfolio_name": "Value Equity Fund",
        "strategy": "Value factor tilt",
        "aum_usd": 700_000_000,
        "n_holdings": 30,
        "select": "value",
    },
    {
        "portfolio_id": "DIV_INC",
        "portfolio_name": "Dividend Income Fund",
        "strategy": "High dividend yield tilt",
        "aum_usd": 500_000_000,
        "n_holdings": 25,
        "select": "dividend",
    },
]

BENCHMARK_ID = "BM_BROAD500"


def load_inputs():
    sec = pd.read_parquet(PROCESSED_DIR / "security_master.parquet")
    fund = pd.read_parquet(PROCESSED_DIR / "fundamentals.parquet")
    esg = pd.read_parquet(PROCESSED_DIR / "esg_scores.parquet")
    prices = pd.read_parquet(PROCESSED_DIR / "market_prices.parquet")

    last_px = (
        prices.sort_values("trade_date")
        .groupby("ticker", as_index=False)
        .tail(1)[["ticker", "close"]]
        .rename(columns={"close": "last_close"})
    )

    universe = sec.merge(fund, on="ticker", how="inner").merge(esg, on="ticker", how="left").merge(
        last_px, on="ticker", how="inner"
    )
    universe = universe.dropna(subset=["last_close", "market_cap"])
    return universe


def select_holdings(universe: pd.DataFrame, rule: str, n: int, rng: np.random.Generator) -> pd.DataFrame:
    df = universe.copy()
    if rule == "core":
        pick = df.sort_values("market_cap", ascending=False).head(n)
        raw_weight = pick["market_cap"]
    elif rule == "esg":
        pick = df.sort_values("total_esg_risk_score", ascending=True).head(n)
        raw_weight = 1 / (pick["total_esg_risk_score"].clip(lower=1))
    elif rule == "growth":
        pick = df.dropna(subset=["revenue_growth"]).sort_values("revenue_growth", ascending=False).head(n)
        raw_weight = pick["revenue_growth"].clip(lower=0.001)
    elif rule == "value":
        pick = df.dropna(subset=["trailing_pe"]).query("trailing_pe > 0").sort_values("trailing_pe").head(n)
        raw_weight = 1 / pick["trailing_pe"]
    elif rule == "dividend":
        pick = df.dropna(subset=["dividend_yield"]).query("dividend_yield > 0").sort_values(
            "dividend_yield", ascending=False
        ).head(n)
        raw_weight = pick["dividend_yield"]
    else:
        raise ValueError(rule)

    noise = rng.uniform(0.85, 1.15, size=len(pick))
    weight = (raw_weight.to_numpy() * noise)
    weight = weight / weight.sum()

    out = pick[["ticker"]].copy()
    out["weight"] = weight
    return out


def build_benchmark(universe: pd.DataFrame) -> pd.DataFrame:
    df = universe[["ticker", "market_cap"]].dropna()
    df["weight"] = df["market_cap"] / df["market_cap"].sum()
    df["benchmark_id"] = BENCHMARK_ID
    df["as_of_date"] = AS_OF
    return df[["benchmark_id", "as_of_date", "ticker", "weight"]]


def main() -> None:
    rng = np.random.default_rng(42)
    universe = load_inputs()
    print(f"universe for portfolio construction: {len(universe)} names")

    portfolio_rows = []
    holdings_rows = []

    for cfg in PORTFOLIOS:
        holdings = select_holdings(universe, cfg["select"], cfg["n_holdings"], rng)
        cash_weight = rng.uniform(0.01, 0.03)
        holdings["weight"] = holdings["weight"] * (1 - cash_weight)

        last_close = universe.set_index("ticker")["last_close"]
        holdings["last_close"] = holdings["ticker"].map(last_close)
        holdings["market_value"] = holdings["weight"] * cfg["aum_usd"]
        holdings["shares"] = (holdings["market_value"] / holdings["last_close"]).round(0)
        holdings["portfolio_id"] = cfg["portfolio_id"]
        holdings["as_of_date"] = AS_OF

        holdings_rows.append(
            holdings[["portfolio_id", "as_of_date", "ticker", "shares", "last_close", "market_value", "weight"]]
        )

        portfolio_rows.append(
            {
                "portfolio_id": cfg["portfolio_id"],
                "portfolio_name": cfg["portfolio_name"],
                "strategy": cfg["strategy"],
                "aum_usd": cfg["aum_usd"],
                "cash_weight": cash_weight,
                "benchmark_id": BENCHMARK_ID,
                "as_of_date": AS_OF,
            }
        )

    portfolios_df = pd.DataFrame(portfolio_rows)
    holdings_df = pd.concat(holdings_rows, ignore_index=True)
    benchmark_df = build_benchmark(universe)

    portfolios_df.to_parquet(PROCESSED_DIR / "portfolios.parquet", index=False)
    holdings_df.to_parquet(PROCESSED_DIR / "portfolio_holdings.parquet", index=False)
    benchmark_df.to_parquet(PROCESSED_DIR / "benchmark_weights.parquet", index=False)

    print(f"portfolios: {len(portfolios_df)}")
    print(f"portfolio_holdings: {len(holdings_df)} rows across {holdings_df['portfolio_id'].nunique()} portfolios")
    print(f"benchmark_weights: {len(benchmark_df)} rows")


if __name__ == "__main__":
    main()
