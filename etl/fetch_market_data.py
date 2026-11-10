"""
Market data ingestion.

Mimics a daily pricing feed a market-data vendor (Bloomberg / Morgan Stanley /
Refinitiv) would deliver to a data engineering team: adjusted daily OHLCV bars
per security. Source: Yahoo Finance via yfinance.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yfinance as yf

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

CHUNK_SIZE = 50


def load_universe(limit: int | None) -> pd.DataFrame:
    sec_master = pd.read_parquet(PROCESSED_DIR / "security_master.parquet")
    if limit:
        sec_master = sec_master.head(limit)
    return sec_master


def download_chunk(tickers: list[str], period: str) -> pd.DataFrame:
    raw = yf.download(
        tickers=tickers,
        period=period,
        auto_adjust=True,
        group_by="ticker",
        threads=True,
        progress=False,
    )

    frames = []
    # yfinance returns a flat frame when len(tickers) == 1
    if len(tickers) == 1:
        df = raw.copy()
        df["ticker"] = tickers[0]
        frames.append(df)
    else:
        for ticker in tickers:
            if ticker not in raw.columns.get_level_values(0):
                continue
            df = raw[ticker].copy()
            df["ticker"] = ticker
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames)
    out = out.reset_index().rename(
        columns={
            "Date": "trade_date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    return out[["trade_date", "ticker", "open", "high", "low", "close", "volume"]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100, help="number of tickers from the security master universe (default 100; use 0 for all)")
    parser.add_argument("--period", type=str, default="2y", help="yfinance period string, e.g. 1y, 2y, 5y")
    args = parser.parse_args()

    universe = load_universe(args.limit or None)
    tickers = universe["yfinance_ticker"].dropna().unique().tolist()
    print(f"Downloading {len(tickers)} tickers, period={args.period}")

    chunks = []
    for i in range(0, len(tickers), CHUNK_SIZE):
        batch = tickers[i : i + CHUNK_SIZE]
        print(f"  chunk {i // CHUNK_SIZE + 1}: {batch[0]}..{batch[-1]} ({len(batch)} tickers)")
        chunks.append(download_chunk(batch, args.period))

    prices = pd.concat(chunks, ignore_index=True)
    prices = prices.dropna(subset=["close"])
    prices["trade_date"] = pd.to_datetime(prices["trade_date"]).dt.date

    # map back to the primary security-master ticker (handles BRK-B vs BRK.B)
    ticker_map = dict(zip(universe["yfinance_ticker"], universe["ticker"]))
    prices["ticker"] = prices["ticker"].map(ticker_map).fillna(prices["ticker"])

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    prices.to_parquet(PROCESSED_DIR / "market_prices.parquet", index=False)

    print(f"market_prices: {len(prices)} rows, {prices['ticker'].nunique()} tickers, "
          f"{prices['trade_date'].min()}..{prices['trade_date'].max()}")


if __name__ == "__main__":
    main()
