import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.auth import hash_key
from app.main import app

STANDARD_KEY = "test-standard-key"
CONFIDENTIAL_KEY = "test-confidential-key"
NO_SCOPE_KEY = "test-no-scope-key"

_KEY_RECORDS = {
    hash_key(STANDARD_KEY): {"client_name": "standard-client", "scopes": {"standard:read"}},
    hash_key(CONFIDENTIAL_KEY): {
        "client_name": "confidential-client",
        "scopes": {"standard:read", "confidential:read"},
    },
    hash_key(NO_SCOPE_KEY): {"client_name": "no-scope-client", "scopes": set()},
}


@pytest.fixture(autouse=True)
def fake_key_cache(monkeypatch):
    """Every test gets a fixed, in-memory API-key table instead of hitting BigQuery."""
    monkeypatch.setattr("app.auth._cached_keys", lambda: _KEY_RECORDS)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def standard_headers():
    return {"X-API-Key": STANDARD_KEY}


@pytest.fixture
def confidential_headers():
    return {"X-API-Key": CONFIDENTIAL_KEY}


def df(rows: list[dict]) -> pd.DataFrame:
    """Build a DataFrame the way a real BigQuery result would come back,
    preserving column order/presence even when rows is empty."""
    return pd.DataFrame(rows)
