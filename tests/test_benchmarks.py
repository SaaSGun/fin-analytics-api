from tests.conftest import df


def test_get_constituents_found(client, standard_headers, monkeypatch):
    constituent = {"ticker": "AAPL", "company_name": "Apple Inc.", "gics_sector": "Information Technology", "weight": 0.07}
    monkeypatch.setattr("app.routers.benchmarks.run_query", lambda sql, params=None: df([constituent]))

    resp = client.get("/benchmarks/BM_BROAD500/constituents", headers=standard_headers)

    assert resp.status_code == 200
    assert resp.json()["data"][0]["ticker"] == "AAPL"


def test_get_constituents_unknown_benchmark_404(client, standard_headers, monkeypatch):
    monkeypatch.setattr("app.routers.benchmarks.run_query", lambda sql, params=None: df([]))

    resp = client.get("/benchmarks/NOPE/constituents", headers=standard_headers)

    assert resp.status_code == 404


def test_get_constituents_no_api_key_401(client):
    resp = client.get("/benchmarks/BM_BROAD500/constituents")
    assert resp.status_code == 401
