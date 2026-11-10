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


def test_esg_summary_found(client, confidential_headers, monkeypatch):
    monkeypatch.setattr("app.deps.run_query", lambda sql, params=None: df([PORTFOLIO_META_ROW]))

    agg_row = {"port_total": 18.0, "port_env": 5.0, "port_soc": 6.0, "port_gov": 7.0, "bench_total": 22.5}
    dist_rows = [{"risk_category": "Low", "weight": 0.8}, {"risk_category": "Medium", "weight": 0.2}]
    responses = iter([df([agg_row]), df(dist_rows)])
    monkeypatch.setattr("app.routers.esg.run_query", lambda sql, params=None: next(responses))

    resp = client.get("/portfolios/ESG_LEAD/esg-summary", headers=confidential_headers)

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["portfolio_weighted_esg_risk_score"] == 18.0
    assert body["benchmark_weighted_esg_risk_score"] == 22.5
    assert body["risk_category_weights"] == {"Low": 0.8, "Medium": 0.2}


def test_esg_summary_unknown_portfolio_404(client, confidential_headers, monkeypatch):
    monkeypatch.setattr("app.deps.run_query", lambda sql, params=None: df([]))

    resp = client.get("/portfolios/NOPE/esg-summary", headers=confidential_headers)

    assert resp.status_code == 404


def test_esg_summary_requires_confidential_scope(client, standard_headers):
    resp = client.get("/portfolios/ESG_LEAD/esg-summary", headers=standard_headers)
    assert resp.status_code == 403


def test_esg_laggards_found(client, confidential_headers, monkeypatch):
    monkeypatch.setattr("app.deps.run_query", lambda sql, params=None: df([PORTFOLIO_META_ROW]))
    laggard = {
        "ticker": "XOM",
        "company_name": "Exxon Mobil",
        "gics_sector": "Energy",
        "weight": 0.05,
        "total_esg_risk_score": 45.0,
        "risk_category": "High",
        "weighted_risk_contribution": 2.25,
    }
    monkeypatch.setattr("app.routers.esg.run_query", lambda sql, params=None: df([laggard]))

    resp = client.get("/portfolios/ESG_LEAD/esg-laggards", headers=confidential_headers)

    assert resp.status_code == 200
    assert resp.json()["data"][0]["ticker"] == "XOM"


def test_esg_laggards_default_limit_is_10(client, confidential_headers, monkeypatch):
    monkeypatch.setattr("app.deps.run_query", lambda sql, params=None: df([PORTFOLIO_META_ROW]))
    monkeypatch.setattr("app.routers.esg.run_query", lambda sql, params=None: df([]))

    resp = client.get("/portfolios/ESG_LEAD/esg-laggards", headers=confidential_headers)

    assert resp.status_code == 200
    assert resp.json()["meta"]["pagination"]["limit"] == 10


def test_screen_securities_requires_only_standard_scope(client, standard_headers, monkeypatch):
    monkeypatch.setattr("app.routers.esg.run_query", lambda sql, params=None: df([]))

    resp = client.get("/esg/screen", headers=standard_headers)

    assert resp.status_code == 200


def test_screen_securities_passes_filters_as_params(client, standard_headers, monkeypatch):
    seen = {}

    def fake_run_query(sql, params=None):
        seen.update({p.name: p.value for p in params})
        return df([])

    monkeypatch.setattr("app.routers.esg.run_query", fake_run_query)

    client.get(
        "/esg/screen",
        headers=standard_headers,
        params={"sector": "Energy", "max_risk_score": 30, "min_market_cap": 1_000_000},
    )

    assert seen["sector"] == "Energy"
    assert seen["max_risk_score"] == 30
    assert seen["min_market_cap"] == 1_000_000
