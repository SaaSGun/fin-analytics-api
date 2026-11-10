def test_health_is_bare_not_enveloped(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_ready_ok_when_bigquery_reachable(client, monkeypatch):
    monkeypatch.setattr("app.main.get_client", lambda: _OkClient())
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_ready_503_when_bigquery_unreachable(client, monkeypatch):
    monkeypatch.setattr("app.main.get_client", lambda: _FailingClient())
    resp = client.get("/health/ready")
    assert resp.status_code == 503


class _OkClient:
    def query(self, _sql):
        return self

    def result(self, timeout=None):
        return None


class _FailingClient:
    def query(self, _sql):
        raise RuntimeError("connection refused")
