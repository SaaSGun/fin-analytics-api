"""API-key authentication and scope-based authorization.

Callers send their key in the `X-API-Key` header. Each key is granted a
set of scopes - {standard,confidential} x {read,write} - stored in the
`api_keys` BigQuery table (managed via scripts/manage_api_keys.py).
Routes declare what they require via `require_scopes(...)`.

Keys are looked up by SHA-256 hash; the raw key is never persisted.
Granted scopes are cached in memory and refreshed every CACHE_TTL_SECONDS,
so a newly revoked key can stay valid on an already-warm instance for up
to that long.
"""
from __future__ import annotations

import hashlib
import time

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from google.api_core.exceptions import NotFound

from app.bigquery_client import get_client
from app.config import get_settings
from app.observability import set_client_name
from app.rate_limit import check_rate_limit

CACHE_TTL_SECONDS = 300

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_cache: dict[str, dict] = {}
# -inf, not 0.0: time.monotonic()'s epoch is unspecified and can start near
# zero in a freshly-started sandboxed container, which would make the first
# staleness check below false and serve the empty default cache forever.
_cache_loaded_at: float = float("-inf")


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _load_keys() -> dict[str, dict]:
    settings = get_settings()
    table = f"{settings.gcp_project_id}.{settings.bq_dataset}.api_keys"
    try:
        rows = get_client().query(
            f"SELECT key_hash, client_name, scopes FROM `{table}` WHERE active"
        ).result()
    except NotFound:
        return {}
    return {row.key_hash: {"client_name": row.client_name, "scopes": set(row.scopes)} for row in rows}


def _cached_keys() -> dict[str, dict]:
    global _cache, _cache_loaded_at
    if time.monotonic() - _cache_loaded_at > CACHE_TTL_SECONDS:
        _cache = _load_keys()
        _cache_loaded_at = time.monotonic()
    return _cache


def require_scopes(*required_scopes: str):
    """FastAPI dependency factory: raises 401/403/429, else returns the caller's client_name."""
    required = set(required_scopes)

    def _dependency(api_key: str | None = Security(_api_key_header)) -> str:
        if api_key is None:
            raise HTTPException(status_code=401, detail="missing API key")
        record = _cached_keys().get(hash_key(api_key))
        if record is None:
            raise HTTPException(status_code=401, detail="invalid API key")
        set_client_name(record["client_name"])
        if not required.issubset(record["scopes"]):
            raise HTTPException(status_code=403, detail="insufficient scope")
        check_rate_limit(record["client_name"])
        return record["client_name"]

    return _dependency
