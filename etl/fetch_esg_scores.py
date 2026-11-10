"""
ESG ratings ingestion.

At a real investment manager, ESG pillar/risk scores are licensed from a
ratings provider (MSCI ESG, Sustainalytics, etc.) and loaded as a vendor
feed alongside the security master. Yahoo Finance exposes Sustainalytics-
sourced ESG risk scores for a subset of tickers (Ticker.sustainability),
which this script uses as a real-world-shaped stand-in for that feed.

Coverage from the free Yahoo endpoint is partial and can disappear for a
given ticker at any time, so this script always falls back to a clearly
labelled synthetic score (sector-correlated, deterministic per ticker) for
any name with no vendor data, instead of silently dropping it. Downstream
consumers can filter on `source` to distinguish real vendor data from the
synthetic fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"

# Rough sector risk tilts used only to make the synthetic fallback plausible;
# not a representation of any real rating methodology.
SECTOR_RISK_TILT = {
    "Energy": 6,
    "Utilities": 4,
    "Materials": 5,
    "Industrials": 2,
    "Consumer Staples": -2,
    "Health Care": -3,
    "Financials": -1,
    "Information Technology": -3,
    "Communication Services": -1,
    "Consumer Discretionary": 0,
    "Real Estate": -1,
}


def fetch_vendor_esg(ticker: str) -> dict | None:
    sustainability = yf.Ticker(ticker).sustainability
    if sustainability is None or sustainability.empty:
        return None
    s = sustainability["Value"] if "Value" in sustainability.columns else sustainability.iloc[:, 0]
    s.index = [str(i).lower() for i in s.index]

    def get(key):
        return s.get(key)

    total = get("totalesg")
    if total is None or pd.isna(total):
        return None

    return {
        "source": "yahoo_sustainalytics",
        "total_esg_risk_score": float(total),
        "environment_risk_score": float(get("environmentscore")) if get("environmentscore") is not None else None,
        "social_risk_score": float(get("socialscore")) if get("socialscore") is not None else None,
        "governance_risk_score": float(get("governancescore")) if get("governancescore") is not None else None,
        "controversy_level": get("highestcontroversy"),
    }


def synthetic_esg(ticker: str, sector: str) -> dict:
    seed = int(hashlib.sha256(ticker.encode()).hexdigest(), 16) % (2**32)
    rng = np.random.default_rng(seed)

    base = 20 + SECTOR_RISK_TILT.get(sector, 0)
    total = float(np.clip(rng.normal(base, 6), 2, 45))
    env = float(np.clip(total * rng.uniform(0.25, 0.45), 0, 40))
    soc = float(np.clip(total * rng.uniform(0.25, 0.4), 0, 40))
    gov = float(np.clip(total - env - soc, 0, 40))

    return {
        "source": "synthetic_fallback",
        "total_esg_risk_score": round(total, 1),
        "environment_risk_score": round(env, 1),
        "social_risk_score": round(soc, 1),
        "governance_risk_score": round(gov, 1),
        "controversy_level": int(rng.integers(0, 5)),
    }


def risk_category(total: float) -> str:
    if total < 10:
        return "Negligible"
    if total < 20:
        return "Low"
    if total < 30:
        return "Medium"
    if total < 40:
        return "High"
    return "Severe"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    universe = pd.read_parquet(PROCESSED_DIR / "security_master.parquet")
    if args.limit:
        universe = universe.head(args.limit)

    rows = []
    n_vendor = 0
    for i, (_, sec) in enumerate(universe.iterrows()):
        ticker, yft, sector = sec["ticker"], sec["yfinance_ticker"], sec["gics_sector"]
        try:
            vendor = fetch_vendor_esg(yft)
        except Exception:  # noqa: BLE001 - any vendor failure falls back to synthetic
            vendor = None

        row = vendor if vendor else synthetic_esg(ticker, sector)
        if vendor:
            n_vendor += 1
        row["ticker"] = ticker
        rows.append(row)

        if i % 20 == 0:
            print(f"  scored {i + 1}/{len(universe)} (vendor hits so far: {n_vendor})")
        time.sleep(0.05)

    df = pd.DataFrame(rows)
    df["risk_category"] = df["total_esg_risk_score"].apply(risk_category)
    df = df[
        [
            "ticker",
            "source",
            "total_esg_risk_score",
            "environment_risk_score",
            "social_risk_score",
            "governance_risk_score",
            "controversy_level",
            "risk_category",
        ]
    ]

    df.to_parquet(PROCESSED_DIR / "esg_scores.parquet", index=False)
    print(f"esg_scores: {len(df)} rows, vendor-sourced={n_vendor}, synthetic={len(df) - n_vendor}")
    print(df.head(3).to_string())


if __name__ == "__main__":
    main()
