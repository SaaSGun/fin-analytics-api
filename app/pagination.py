"""
Cursor-based pagination helpers.

Every list endpoint accepts `cursor` (opaque, taken verbatim from a
previous response's `meta.pagination.next_cursor`) and `limit`, and is
sorted by a stable keyset (a unique column, or a column plus a tiebreaker
column when the primary sort column can repeat). The cursor encodes the
last-seen row's keyset values; the next page's WHERE clause resumes right
after that row instead of using OFFSET, so results stay correct even if
rows are inserted/removed between page fetches.
"""
from __future__ import annotations

import base64
import json
from datetime import date as _date
from typing import Any

from fastapi import HTTPException, Query

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


def cursor_query(
    description: str = "Opaque pagination cursor, taken from a previous response's meta.pagination.next_cursor",
) -> Any:
    return Query(None, description=description)


def limit_query(default: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT) -> Any:
    return Query(default, ge=1, le=max_limit, description=f"max rows to return (1-{max_limit})")


def encode_cursor(fields: dict[str, Any]) -> str:
    payload = json.dumps(fields, default=str, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if cursor is None:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except ValueError:  # covers binascii.Error, JSONDecodeError, UnicodeDecodeError
        raise HTTPException(status_code=400, detail="invalid cursor")


def cursor_date(decoded: dict[str, Any] | None, field: str) -> _date | None:
    if not decoded or field not in decoded:
        return None
    return _date.fromisoformat(decoded[field])


def paginate(
    rows: list[dict[str, Any]], limit: int, cursor_fields: tuple[str, ...]
) -> tuple[list[dict[str, Any]], str | None, bool]:
    """rows must already be sorted by the endpoint's keyset order and
    fetched with LIMIT limit+1. Trims to `limit` and builds the next
    cursor from the last kept row's `cursor_fields` values."""
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = encode_cursor({f: page[-1][f] for f in cursor_fields}) if has_more and page else None
    return page, next_cursor, has_more
