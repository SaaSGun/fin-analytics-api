"""
Security master ingestion.

Mimics the reference-data feed a buy-side data engineering team would receive
from an index/data provider (e.g. MSCI/S&P) describing index membership,
GICS sector classification, and basic identifiers. Source: Wikipedia's
"List of S&P 500 companies" (public domain aggregation of SEC/S&P public data).
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
HEADERS = {"User-Agent": "fin-analytics-api-demo/1.0 (data pipeline test)"}

RENAME_MAP = {
    "Symbol": "ticker",
    "Security": "company_name",
    "GICS Sector": "gics_sector",
    "GICS Sub-Industry": "gics_sub_industry",
    "Headquarters Location": "hq_location",
    "Date added": "date_added",
    "CIK": "cik",
    "Founded": "founded",
}


def fetch_raw_html() -> str:
    resp = requests.get(WIKI_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def clean_security_master(raw_html: str) -> pd.DataFrame:
    tables = pd.read_html(io.StringIO(raw_html))
    df = tables[0].rename(columns=RENAME_MAP)

    # yfinance / most market data vendors use '-' instead of '.' in share classes
    df["yfinance_ticker"] = df["ticker"].str.replace(".", "-", regex=False)

    df["date_added"] = pd.to_datetime(df["date_added"], errors="coerce").dt.date
    df["cik"] = df["cik"].astype(str).str.zfill(10)
    # Wikipedia's "Headquarters Location" is "City, State" for these (almost all US) companies.
    df["hq_state"] = df["hq_location"].str.split(",").str[-1].str.strip()

    df = df[
        [
            "ticker",
            "yfinance_ticker",
            "company_name",
            "gics_sector",
            "gics_sub_industry",
            "hq_location",
            "hq_state",
            "date_added",
            "cik",
            "founded",
        ]
    ].drop_duplicates(subset=["ticker"]).reset_index(drop=True)

    return df


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    html = fetch_raw_html()
    (RAW_DIR / "sp500_wikipedia.html").write_text(html, encoding="utf-8")

    df = clean_security_master(html)
    df.to_csv(RAW_DIR / "security_master.csv", index=False)
    df.to_parquet(PROCESSED_DIR / "security_master.parquet", index=False)

    print(f"security_master: {len(df)} rows, {df['gics_sector'].nunique()} sectors")
    print(df.head(3).to_string())


if __name__ == "__main__":
    main()
