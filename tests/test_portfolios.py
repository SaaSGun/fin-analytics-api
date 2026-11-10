from tests.conftest import df

PORTFOLIO_META_ROW = {
    "portfolio_id": "ESG_LEAD",
    "portfolio_name": "ESG Leaders",
    "strategy": "esg_tilt",
    "aum_usd": 100_000_000.0,
    "cash_weight": 0.01,
    "benchmark_id": "BM_BROAD500",
    "as_of_date": "2026-11-06",
}


def test_list_portfolios_requires_confidential_scope(client, standard_headers):
    resp = client.get("/portfolios", headers=standard_headers)
    assert resp.status_code == 403


def test_list_portfolios(client, confidential_headers, monkeypatch):
    monkeypatch.setattr("app.routers.portfolios.run_query", lambda sql, params=None: df([PORTFOLIO_META_ROW]))

    resp = client.get("/portfolios", headers=confidential_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["portfolio_id"] == "ESG_LEAD"
    assert body["meta"]["pagination"]["has_more"] is False


def test_get_holdings_unknown_portfolio_404(client, confidential_headers, monkeypatch):
    monkeypatch.setattr("app.deps.run_query", lambda sql, params=None: df([]))

    resp = client.get("/portfolios/NOPE/holdings", headers=confidential_headers)

    assert resp.status_code == 404


def test_get_holdings_found(client, confidential_headers, monkeypatch):
    monkeypatch.setattr("app.deps.run_query", lambda sql, params=None: df([PORTFOLIO_META_ROW]))
    holding = {
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "gics_sector": "Information Technology",
        "weight": 0.1,
        "shares": 1000.0,
        "market_value": 230_000.0,
    }
    monkeypatch.setattr("app.routers.portfolios.run_query", lambda sql, params=None: df([holding]))

    resp = client.get("/portfolios/ESG_LEAD/holdings", headers=confidential_headers)

    assert resp.status_code == 200
    assert resp.json()["data"][0]["ticker"] == "AAPL"


def test_get_sector_exposures_found(client, confidential_headers, monkeypatch):
    monkeypatch.setattr("app.deps.run_query", lambda sql, params=None: df([PORTFOLIO_META_ROW]))
    exposure = {
        "gics_sector": "Information Technology",
        "portfolio_weight": 0.4,
        "benchmark_weight": 0.3,
        "active_weight": 0.1,
    }
    monkeypatch.setattr("app.routers.portfolios.run_query", lambda sql, params=None: df([exposure]))

    resp = client.get("/portfolios/ESG_LEAD/exposures", headers=confidential_headers)

    assert resp.status_code == 200
    assert resp.json()["data"][0]["active_weight"] == 0.1


def test_get_performance_found(client, confidential_headers, monkeypatch):
    monkeypatch.setattr("app.deps.run_query", lambda sql, params=None: df([PORTFOLIO_META_ROW]))
    point = {"trade_date": "2026-01-02", "portfolio_cum_return": 0.05, "benchmark_cum_return": 0.03}
    monkeypatch.setattr("app.routers.portfolios.run_query", lambda sql, params=None: df([point]))

    resp = client.get("/portfolios/ESG_LEAD/performance", headers=confidential_headers)

    assert resp.status_code == 200
    assert resp.json()["data"][0]["portfolio_cum_return"] == 0.05


def test_get_performance_unknown_portfolio_404(client, confidential_headers, monkeypatch):
    monkeypatch.setattr("app.deps.run_query", lambda sql, params=None: df([]))

    resp = client.get("/portfolios/NOPE/performance", headers=confidential_headers)

    assert resp.status_code == 404
