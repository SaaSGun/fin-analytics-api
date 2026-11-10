from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from google.api_core.exceptions import NotFound

from app.auth import _cached_keys as real_cached_keys
from app.auth import _load_keys, hash_key, require_scopes


def test_hash_key_is_deterministic_sha256():
    assert hash_key("abc") == hash_key("abc")
    assert hash_key("abc") != hash_key("abd")
    assert len(hash_key("abc")) == 64  # hex-encoded sha256 digest


def test_missing_api_key_raises_401():
    dependency = require_scopes("standard:read")
    with pytest.raises(HTTPException) as exc_info:
        dependency(api_key=None)
    assert exc_info.value.status_code == 401


def test_unknown_api_key_raises_401(fake_key_cache):
    dependency = require_scopes("standard:read")
    with pytest.raises(HTTPException) as exc_info:
        dependency(api_key="not-a-real-key")
    assert exc_info.value.status_code == 401


def test_insufficient_scope_raises_403(fake_key_cache):
    from tests.conftest import STANDARD_KEY

    dependency = require_scopes("confidential:read")
    with pytest.raises(HTTPException) as exc_info:
        dependency(api_key=STANDARD_KEY)
    assert exc_info.value.status_code == 403


def test_sufficient_scope_returns_client_name(fake_key_cache):
    from tests.conftest import CONFIDENTIAL_KEY

    dependency = require_scopes("confidential:read")
    assert dependency(api_key=CONFIDENTIAL_KEY) == "confidential-client"


def test_requiring_multiple_scopes_needs_all_of_them(fake_key_cache):
    from tests.conftest import CONFIDENTIAL_KEY, STANDARD_KEY

    dependency = require_scopes("standard:read", "confidential:read")
    assert dependency(api_key=CONFIDENTIAL_KEY) == "confidential-client"
    with pytest.raises(HTTPException) as exc_info:
        dependency(api_key=STANDARD_KEY)
    assert exc_info.value.status_code == 403


def test_load_keys_parses_rows_into_scope_sets(monkeypatch):
    row = MagicMock(key_hash="deadbeef", client_name="acme", scopes=["standard:read", "confidential:read"])
    fake_client = MagicMock()
    fake_client.query.return_value.result.return_value = [row]
    monkeypatch.setattr("app.auth.get_client", lambda: fake_client)

    keys = _load_keys()

    assert keys == {"deadbeef": {"client_name": "acme", "scopes": {"standard:read", "confidential:read"}}}


def test_load_keys_table_not_found_returns_empty(monkeypatch):
    fake_client = MagicMock()
    fake_client.query.return_value.result.side_effect = NotFound("no such table")
    monkeypatch.setattr("app.auth.get_client", lambda: fake_client)

    assert _load_keys() == {}


def test_cached_keys_loads_on_first_call_even_if_monotonic_clock_starts_near_zero(monkeypatch):
    # time.monotonic()'s epoch is unspecified - a freshly-started sandboxed
    # container can have it start near 0. If the staleness check ever
    # compared against a 0.0 "never loaded" sentinel, a small first reading
    # would wrongly look "fresh" and skip loading entirely (the bug this
    # guards against: see the -inf default in app/auth.py).
    import app.auth as auth_module

    # deliberately NOT monkeypatching _cache_loaded_at - this must exercise
    # the real module-level default to actually guard the sentinel's value.
    monkeypatch.setattr(auth_module, "_cache", {})
    monkeypatch.setattr(auth_module.time, "monotonic", lambda: 1.0)
    loaded = {"deadbeef": {"client_name": "fresh-instance", "scopes": {"standard:read"}}}
    monkeypatch.setattr(auth_module, "_load_keys", lambda: loaded)

    assert real_cached_keys() == loaded
