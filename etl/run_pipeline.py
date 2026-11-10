"""Runs the full ETL pipeline end to end: fetch -> clean -> generate -> load."""
from __future__ import annotations

import sys

import fetch_esg_scores
import fetch_fundamentals
import fetch_market_data
import fetch_security_master
import generate_portfolios
import load_bigquery


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100

    print("== 1/6 security master ==")
    fetch_security_master.main()

    print("== 2/6 market prices ==")
    sys.argv = ["fetch_market_data.py", "--limit", str(limit)]
    fetch_market_data.main()

    print("== 3/6 fundamentals ==")
    sys.argv = ["fetch_fundamentals.py", "--limit", str(limit)]
    fetch_fundamentals.main()

    print("== 4/6 esg scores ==")
    sys.argv = ["fetch_esg_scores.py", "--limit", str(limit)]
    fetch_esg_scores.main()

    print("== 5/6 synthetic portfolios ==")
    generate_portfolios.main()

    print("== 6/6 load to bigquery ==")
    load_bigquery.main()


if __name__ == "__main__":
    main()
