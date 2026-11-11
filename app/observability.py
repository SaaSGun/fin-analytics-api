"""Structured JSON logging for Cloud Logging, plus a per-request log line.

Cloud Run sends each JSON line on stdout to Cloud Logging as a
jsonPayload, and lifts a few special keys out of it: `severity`,
`message`, `httpRequest`, and `logging.googleapis.com/trace`. The trace
key groups every log line of a request together with Cloud Run's own
request log entry.

Request-scoped fields (request_id, client_name, trace) live in a context
variable that the formatter adds to every log line, including the
per-query BigQuery logs from app/bigquery_client.py. The context holds a
mutable dict because the auth dependency and the route handler run in
separate threadpool calls, each with a copy of the request's context. A
value set there would never reach the middleware, but a change to the
shared dict does.
"""
from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

from fastapi import Request

from app.config import get_settings

logger = logging.getLogger("app.requests")

_request_ctx: ContextVar[dict | None] = ContextVar("request_ctx", default=None)


class CloudLoggingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {"severity": record.levelname, "message": record.getMessage(), "logger": record.name}
        entry.update(_request_ctx.get() or {})
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["message"] += "\n" + self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(CloudLoggingFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def set_client_name(client_name: str) -> None:
    ctx = _request_ctx.get()
    if ctx is not None:
        ctx["client_name"] = client_name


async def request_logging_middleware(request: Request, call_next):
    ctx = {"request_id": request.headers.get("x-request-id") or uuid.uuid4().hex, "client_name": None}
    # Format: TRACE_ID/SPAN_ID;o=OPTIONS
    trace_header = request.headers.get("x-cloud-trace-context")
    if trace_header:
        trace_id = trace_header.split("/")[0]
        ctx["logging.googleapis.com/trace"] = f"projects/{get_settings().gcp_project_id}/traces/{trace_id}"
    token = _request_ctx.set(ctx)

    start = time.perf_counter()
    status, error = 500, None  # 500 if call_next raises - what ServerErrorMiddleware will answer
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception as exc:
        error = exc
        raise
    finally:
        level = logging.ERROR if status >= 500 else logging.WARNING if status >= 400 else logging.INFO
        logger.log(
            level,
            "%s %s %s",
            request.method,
            request.url.path,
            status,
            exc_info=error,
            extra={
                "fields": {
                    "event": "request",
                    "httpRequest": {
                        "requestMethod": request.method,
                        "requestUrl": str(request.url),
                        "status": status,
                        "latency": f"{time.perf_counter() - start:.3f}s",
                        "userAgent": request.headers.get("user-agent"),
                        "remoteIp": request.client.host if request.client else None,
                    },
                }
            },
        )
        _request_ctx.reset(token)

    response.headers["X-Request-ID"] = ctx["request_id"]
    return response
