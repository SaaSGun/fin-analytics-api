"""Per-client token-bucket rate limiting.

Each authenticated client (keyed by the client_name that require_scopes
resolves) gets a bucket of RATE_LIMIT_BURST tokens, refilled at
RATE_LIMIT_PER_SECOND. Every request spends one token; an empty bucket
means 429 + Retry-After. The main point is cost control: every request
that misses the result cache is a billed BigQuery query. The public
/health/ready check has no client, so it gets a bucket per caller IP
(see caller_ip).

State is in memory per Cloud Run instance, not shared. A client whose
requests are spread over N instances can get up to N x its nominal limit
(max-instances is 10). That's acceptable for this project; a shared limit
would need Redis/Memorystore.
"""
from __future__ import annotations

import ipaddress
import math
import threading
import time

from fastapi import HTTPException, Request

from app.config import get_settings

_buckets: dict[str, tuple[float, float]] = {}  # client_name -> (tokens, last refill time)
_lock = threading.Lock()  # route dependencies run in the threadpool
# Per-IP keys come from the open internet, so the dict must not grow forever.
_MAX_BUCKETS = 10_000


def caller_ip(request: Request) -> str:
    """The caller's IP address, or its /64 network for IPv6.

    On Cloud Run, request.client is Cloud Run's internal proxy (169.254.x.x),
    the same for every caller. Google's front end appends the address it got
    the request from to X-Forwarded-For, so the last entry is the real
    caller; anything before it came from the caller and can be forged. An
    IPv6 host usually controls a whole /64, so the limit applies per /64.
    """
    ip = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    if not ip:  # not behind Cloud Run, e.g. local uvicorn
        ip = request.client.host if request.client else "unknown"
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


def check_rate_limit(client_name: str) -> None:
    settings = get_settings()
    rate, burst = settings.rate_limit_per_second, settings.rate_limit_burst
    now = time.monotonic()
    with _lock:
        if len(_buckets) > _MAX_BUCKETS:
            # A bucket left alone for burst/rate seconds is full again, which
            # is the same as having no entry, so dropping it changes nothing.
            full_after = burst / rate
            for key in [k for k, (_, seen) in _buckets.items() if now - seen >= full_after]:
                del _buckets[key]
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
