"""Per-client token-bucket rate limiting.

Each authenticated client (keyed by the client_name that require_scopes
resolves) gets a bucket of RATE_LIMIT_BURST tokens, refilled at
RATE_LIMIT_PER_SECOND. Every request spends one token; an empty bucket
means 429 + Retry-After. The main point is cost control: every request
that misses the result cache is a billed BigQuery query.

State is in memory per Cloud Run instance, not shared. A client whose
requests are spread over N instances can get up to N x its nominal limit
(max-instances is 10). That's acceptable for this project; a shared limit
would need Redis/Memorystore.
"""
from __future__ import annotations

import math
import threading
import time

from fastapi import HTTPException

from app.config import get_settings

_buckets: dict[str, tuple[float, float]] = {}  # client_name -> (tokens, last refill time)
_lock = threading.Lock()  # route dependencies run in the threadpool


def check_rate_limit(client_name: str) -> None:
    settings = get_settings()
    rate, burst = settings.rate_limit_per_second, settings.rate_limit_burst
    now = time.monotonic()
    with _lock:
        tokens, last = _buckets.get(client_name, (burst, now))
        tokens = min(burst, tokens + (now - last) * rate)
        allowed = tokens >= 1
        _buckets[client_name] = (tokens - 1 if allowed else tokens, now)
    if not allowed:
        retry_after = math.ceil((1 - tokens) / rate)
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
