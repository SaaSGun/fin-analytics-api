from datetime import date

import pytest
from fastapi import HTTPException

from app.pagination import cursor_date, decode_cursor, encode_cursor, paginate


def test_encode_decode_roundtrip():
    fields = {"ticker": "AAPL", "weight": 0.1234}
    assert decode_cursor(encode_cursor(fields)) == fields


def test_decode_cursor_none_is_none():
    assert decode_cursor(None) is None


def test_decode_cursor_invalid_raises_400():
    with pytest.raises(HTTPException) as exc_info:
        decode_cursor("not-valid-base64-json!!!")
    assert exc_info.value.status_code == 400


def test_cursor_date_missing_field_returns_none():
    assert cursor_date({"other": "x"}, "trade_date") is None
    assert cursor_date(None, "trade_date") is None


def test_cursor_date_parses_iso_string():
    decoded = {"trade_date": "2026-01-15"}
    assert cursor_date(decoded, "trade_date") == date(2026, 1, 15)


def test_paginate_fewer_rows_than_limit_no_more_pages():
    rows = [{"ticker": "A"}, {"ticker": "B"}]
    page, next_cursor, has_more = paginate(rows, limit=5, cursor_fields=("ticker",))
    assert page == rows
    assert has_more is False
    assert next_cursor is None


def test_paginate_exactly_limit_rows_no_more_pages():
    rows = [{"ticker": "A"}, {"ticker": "B"}]
    page, next_cursor, has_more = paginate(rows, limit=2, cursor_fields=("ticker",))
    assert page == rows
    assert has_more is False
    assert next_cursor is None


def test_paginate_more_rows_than_limit_builds_next_cursor():
    rows = [{"ticker": "A"}, {"ticker": "B"}, {"ticker": "C"}]
    page, next_cursor, has_more = paginate(rows, limit=2, cursor_fields=("ticker",))
    assert page == rows[:2]
    assert has_more is True
    assert decode_cursor(next_cursor) == {"ticker": "B"}


def test_paginate_empty_rows():
    page, next_cursor, has_more = paginate([], limit=10, cursor_fields=("ticker",))
    assert page == []
    assert has_more is False
    assert next_cursor is None


def test_paginate_multi_field_cursor():
    rows = [{"weight": 0.5, "ticker": "A"}, {"weight": 0.3, "ticker": "B"}, {"weight": 0.1, "ticker": "C"}]
    page, next_cursor, has_more = paginate(rows, limit=2, cursor_fields=("weight", "ticker"))
    assert decode_cursor(next_cursor) == {"weight": 0.3, "ticker": "B"}
