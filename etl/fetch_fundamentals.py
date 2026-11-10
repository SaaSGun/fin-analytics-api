"""
Fundamentals / company-profile snapshot ingestion.

Mimics a vendor fundamentals feed (market cap, valuation multiples, risk
stats) that would land in a firm's analytics warehouse alongside pricing and
reference data. Source: Yahoo Finance via yfinance (Ticker.get_info()).
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"

FIELDS = {
    "marketCap": "market_cap",
    "trailingPE": "trailing_pe",
    "forwardPE": "forward_pe",
    "dividendYield": "dividend_yield",
    "beta": "beta",
    "fiftyTwoWeekHigh": "fifty_two_week_high",
    "fiftyTwoWeekLow": "fifty_two_week_low",
    "currency": "currency",
    "country": "country",
    "fullTimeEmployees": "full_time_employees",
    "returnOnEquity": "return_on_equity",
    "profitMargins": "profit_margins",
    "revenueGrowth": "revenue_growth",
    "debtToEquity": "debt_to_equity",
}


def fetch_one(ticker: str) -> dict:
    info = yf.Ticker(ticker).get_info()
    row = {"ticker": ticker}
    for src, dst in FIELDS.items():
        row[dst] = info.get(src) 
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    universe = pd.read_parquet(PROCESSED_DIR / "security_master.parquet")
    if args.limit:
        universe = universe.head(args.limit)

    rows = []
    for i, (_, sec) in enumerate(universe.iterrows()):
        yft = sec["yfinance_ticker"]
        try:
            row = fetch_one(yft)
            row["ticker"] = sec["ticker"]
            rows.append(row)
        except Exception as exc:  # noqa: BLE001 - vendor flakiness, skip ticker
            print(f"  skip {yft}: {exc}")
        if i % 20 == 0:
            print(f"  fetched {i + 1}/{len(universe)}")
        time.sleep(0.1)

    df = pd.DataFrame(rows)
    df.to_parquet(PROCESSED_DIR / "fundamentals.parquet", index=False)
    print(f"fundamentals: {len(df)} rows")
    print(df.head(3).to_string())


if __name__ == "__main__":
    main()
