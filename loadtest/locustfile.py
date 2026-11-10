"""
Locust load test for the Fin Analytics API.

Run against the authenticated Cloud Run proxy (in a separate terminal,
left running):
    gcloud run services proxy fin-analytics-api --region europe-west4 \
        --project fin-analytics-api --port 8080

Then, with a key from `scripts/manage_api_keys.py create` in
LOAD_TEST_API_KEY:
    set LOAD_TEST_API_KEY=<raw key>
    python -m locust -f loadtest/locustfile.py --host http://localhost:8080

Opens a web UI at http://localhost:8089 to pick user count/ramp rate and
watch live charts. For a scripted headless run instead:
    python -m locust -f loadtest/locustfile.py --host http://localhost:8080 ^
        --headless -u 50 -r 5 -t 2m --csv loadtest/results

Tickers/portfolio/benchmark IDs below are real values confirmed present in
the currently loaded BigQuery tables (100-ticker subset), not guessed.

Cache-miss mode: `set LOAD_TEST_VARY_PARAMS=1` randomises `limit` on every
list endpoint (plus `start`/`end` on prices and performance, and the ESG
screen threshold), so nearly every request is a distinct query that misses
the API's per-instance result cache and really hits BigQuery. Stats are
then grouped by route (e.g. `/securities/[ticker]/prices`) instead of by
full URL. `/securities/{ticker}` takes no params and still cycles through
the 10 tickers, so it stays mostly cached in this mode too.
"""
import datetime
import os
import random

from locust import HttpUser, between, task

API_KEY = os.environ.get("LOAD_TEST_API_KEY", "")
VARY_PARAMS = os.environ.get("LOAD_TEST_VARY_PARAMS") == "1"

# market_prices coverage in the loaded data.
DATA_START, DATA_END = datetime.date(2024, 11, 7), datetime.date(2026, 11, 6)


def _random_limit() -> int:
    return random.randint(1, 500)


def _random_date_range() -> dict:
    start = DATA_START + datetime.timedelta(days=random.randint(0, (DATA_END - DATA_START).days - 30))
    end = min(start + datetime.timedelta(days=random.randint(30, 365)), DATA_END)
    return {"start": start.isoformat(), "end": end.isoformat()}


def _name(route: str) -> str | None:
    # Group by route in vary mode, else Locust makes one stats row per URL.
    return route if VARY_PARAMS else None

TICKERS = ["AAPL", "AMZN", "GOOGL", "AVGO", "BKNG", "CAT", "CVX", "BLK", "BAC", "BA"]
PORTFOLIO_IDS = ["CORE_EQ", "ESG_LEAD", "GROWTH", "VALUE", "DIV_INC"]
BENCHMARK_ID = "BM_BROAD500"


class FinApiUser(HttpUser):
    wait_time = between(0.2, 1.0)

    def on_start(self):
        self.client.headers.update({"X-API-Key": API_KEY})

    @task(3)
    def health(self):
        self.client.get("/health")

    @task(5)
    def security_profile(self):
        self.client.get(f"/securities/{random.choice(TICKERS)}")

    @task(4)
    def security_prices(self):
        params = {"limit": _random_limit(), **_random_date_range()} if VARY_PARAMS else {"limit": 100}
        self.client.get(f"/securities/{random.choice(TICKERS)}/prices", params=params,
                        name=_name("/securities/[ticker]/prices"))

    @task(3)
    def list_portfolios(self):
        params = {"limit": _random_limit()} if VARY_PARAMS else None
        self.client.get("/portfolios", params=params, name=_name("/portfolios"))

    @task(3)
    def portfolio_holdings(self):
        params = {"limit": _random_limit()} if VARY_PARAMS else None
        self.client.get(f"/portfolios/{random.choice(PORTFOLIO_IDS)}/holdings", params=params,
                        name=_name("/portfolios/[id]/holdings"))

    @task(2)
    def portfolio_exposures(self):
        params = {"limit": _random_limit()} if VARY_PARAMS else None
        self.client.get(f"/portfolios/{random.choice(PORTFOLIO_IDS)}/exposures", params=params,
                        name=_name("/portfolios/[id]/exposures"))

    @task(1)
    def portfolio_performance(self):
        # Heaviest query of the bunch: window functions over the full
        # market_prices join, so it's weighted lowest, like a real traffic mix.
        params = {"limit": _random_limit(), **_random_date_range()} if VARY_PARAMS else None
        self.client.get(f"/portfolios/{random.choice(PORTFOLIO_IDS)}/performance", params=params,
                        name=_name("/portfolios/[id]/performance"))

    @task(2)
    def esg_screen(self):
        params = ({"max_risk_score": round(random.uniform(10, 40), 1), "limit": _random_limit()}
                  if VARY_PARAMS else {"max_risk_score": 30})
        self.client.get("/esg/screen", params=params, name=_name("/esg/screen"))

    @task(1)
    def benchmark_constituents(self):
        params = {"limit": _random_limit()} if VARY_PARAMS else None
        self.client.get(f"/benchmarks/{BENCHMARK_ID}/constituents", params=params,
                        name=_name("/benchmarks/[id]/constituents"))
