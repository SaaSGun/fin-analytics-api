from app.pagination import encode_cursor
from tests.conftest import df


def test_get_security_no_api_key_401(client):
    resp = client.get("/securities/AAPL")
    assert resp.status_code == 401


def test_get_security_found(client, standard_headers, monkeypatch):
    row = {
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "gics_sector": "Information Technology",
        "gics_sub_industry": "Technology Hardware",
        "hq_state": "California",
        "market_cap": 3_000_000_000_000.0,
        "trailing_pe": 30.0,
        "forward_pe": 28.0,
        "dividend_yield": 0.005,
        "beta": 1.2,
        "last_close": 230.5,
        "last_trade_date": "2026-11-06",
        "total_esg_risk_score": 18.0,
        "environment_risk_score": 5.0,
        "social_risk_score": 6.0,
        "governance_risk_score": 7.0,
        "esg_risk_category": "Low",
        "esg_source": "synthetic_fallback",
    }
    monkeypatch.setattr("app.routers.securities.run_query", lambda sql, params=None: df([row]))

    resp = client.get("/securities/AAPL", headers=standard_headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["ticker"] == "AAPL"
    assert body["meta"]["pagination"] is None


def test_get_security_not_found_404(client, standard_headers, monkeypatch):
    monkeypatch.setattr("app.routers.securities.run_query", lambda sql, params=None: df([]))

    resp = client.get("/securities/NOPE", headers=standard_headers)

    assert resp.status_code == 404


def test_get_security_ticker_uppercased_in_query(client, standard_headers, monkeypatch):
    seen_params = {}

    def fake_run_query(sql, params=None):
        seen_params["ticker"] = next(p.value for p in params if p.name == "ticker")
        return df([])

    monkeypatch.setattr("app.routers.securities.run_query", fake_run_query)

    client.get("/securities/aapl", headers=standard_headers)

    assert seen_params["ticker"] == "AAPL"


def test_get_prices_paginates(client, standard_headers, monkeypatch):
    rows = [{"trade_date": f"2026-01-0{i}", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 100} for i in range(1, 4)]
    monkeypatch.setattr("app.routers.securities.run_query", lambda sql, params=None: df(rows))

    resp = client.get("/securities/AAPL/prices", headers=standard_headers, params={"limit": 2})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["meta"]["pagination"]["has_more"] is True
    assert body["meta"]["pagination"]["next_cursor"] is not None


def test_get_prices_empty_first_page_404(client, standard_headers, monkeypatch):
    monkeypatch.setattr("app.routers.securities.run_query", lambda sql, params=None: df([]))

    resp = client.get("/securities/NOPE/prices", headers=standard_headers)

    assert resp.status_code == 404


def test_get_prices_empty_later_page_is_not_404(client, standard_headers, monkeypatch):
    monkeypatch.setattr("app.routers.securities.run_query", lambda sql, params=None: df([]))

    cursor = encode_cursor({"trade_date": "2026-01-10"})
    resp = client.get("/securities/AAPL/prices", headers=standard_headers, params={"cursor": cursor})

    assert resp.status_code == 200
    assert resp.json()["data"] == []


def test_get_prices_invalid_cursor_400(client, standard_headers):
    resp = client.get("/securities/AAPL/prices", headers=standard_headers, params={"cursor": "!!!not-valid!!!"})
    assert resp.status_code == 400


def test_confidential_scope_cannot_access_standard_route_without_grant(client, monkeypatch):
    # a key that only has confidential:read (not standard:read) must be rejected here
    from app.auth import hash_key
    from tests.conftest import _KEY_RECORDS

    monkeypatch.setitem(_KEY_RECORDS, hash_key("confidential-only"), {"client_name": "x", "scopes": {"confidential:read"}})
    resp = client.get("/securities/AAPL", headers={"X-API-Key": "confidential-only"})
    assert resp.status_code == 403
