import datetime
import logging
import threading
import time
from functools import lru_cache

import requests
from google.cloud import bigquery
from google.cloud.bigquery.retry import DEFAULT_JOB_RETRY, DEFAULT_RETRY

from app.config import get_settings

logger = logging.getLogger(__name__)

# Under load this service's throughput ceiling is BigQuery's API rate limit
# (~100 requests/s per caller identity, shared by every instance), not
# Cloud Run or BigQuery compute. The warehouse is reloaded once a day by the
# ETL, so caching each distinct (sql, params) result per instance for a few
# minutes is effectively never stale and takes repeat requests off that
# limit entirely.
RESULT_CACHE_TTL_SECONDS = 300
RESULT_CACHE_MAX_ENTRIES = 1024

# When BigQuery does rate-limit, the client's default retries back off
# exponentially for up to 10 min (and job_retry re-runs the whole query for
# longer still), which showed up as 30-120s request hangs. Cap both so an
# overloaded request fails fast; app/main.py turns the resulting RetryError
# into a 503 + Retry-After.
BQ_RETRY_TIMEOUT_SECONDS = 10

_result_cache: dict[tuple, tuple[float, object]] = {}
_result_cache_lock = threading.Lock()

# Matches this service's Cloud Run concurrency / thread-pool size (40, set
# via `gcloud run services update --concurrency 40`). requests' default
# HTTPAdapter pool_maxsize is 10, shared across every request thread via the
# one cached client below - under load, threads beyond the first 10 block
# waiting for a pooled connection before a query is even submitted, which is
# invisible in BigQuery's own job-queue metrics but shows up as request
# latency at the Cloud Run layer.
HTTP_POOL_SIZE = 40


@lru_cache
def get_client() -> bigquery.Client:
    settings = get_settings()
    # JOB_CREATION_OPTIONAL: small queries run as a single jobs.query call
    # with no job created, instead of jobs.insert + 2x jobs.getQueryResults.
    # Under load the 3-calls-per-query path exceeded BigQuery's per-user API
    # rate limit (403 rateLimitExceeded), which the client silently retries
    # with exponential backoff - that was the 30-120s request tail.
    client = bigquery.Client(
        project=settings.gcp_project_id,
        default_job_creation_mode=bigquery.enums.JobCreationMode.JOB_CREATION_OPTIONAL,
    )
    adapter = requests.adapters.HTTPAdapter(pool_connections=HTTP_POOL_SIZE, pool_maxsize=HTTP_POOL_SIZE)
    client._http.mount("https://", adapter)
    return client


def dataset_ref() -> str:
    settings = get_settings()
    return f"{settings.gcp_project_id}.{settings.bq_dataset}"


def run_query(sql: str, params: list | None = None):
    params = params or []
    key = (sql, tuple((p.name, p.type_, p.value) for p in params))
    hit = _result_cache.get(key)
    if hit is not None and time.monotonic() - hit[0] < RESULT_CACHE_TTL_SECONDS:
        return hit[1].copy()  # copy: callers must not be able to mutate the cached frame

    client = get_client()
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    start = time.perf_counter()
    rows = client.query_and_wait(
        sql,
        job_config=job_config,
        retry=DEFAULT_RETRY.with_timeout(BQ_RETRY_TIMEOUT_SECONDS),
        job_retry=DEFAULT_JOB_RETRY.with_timeout(BQ_RETRY_TIMEOUT_SECONDS),
    )
    df = rows.to_dataframe()
    # One line per billed query (result-cache hits above cost nothing and
    # aren't logged). Bytes processed is what on-demand pricing charges for.
    logger.info(
        "bigquery query",
        extra={
            "fields": {
                "event": "bigquery_query",
                "bytes_processed": rows.total_bytes_processed,
                "slot_millis": rows.slot_millis,
                "duration_ms": round((time.perf_counter() - start) * 1000),
                "job_id": rows.job_id,
                "query_id": rows.query_id,
            }
        },
    )

    with _result_cache_lock:
        _result_cache.pop(key, None)  # re-insert at the end, so dict order stays oldest-first
        while len(_result_cache) >= RESULT_CACHE_MAX_ENTRIES:
            _result_cache.pop(next(iter(_result_cache)))
        _result_cache[key] = (time.monotonic(), df)
    return df.copy()


def scalar_param(name: str, value, type_: str | None = None) -> bigquery.ScalarQueryParameter:
    if type_ is None:
        if isinstance(value, bool):
            type_ = "BOOL"
        elif isinstance(value, int):
            type_ = "INT64"
        elif isinstance(value, float):
            type_ = "FLOAT64"
        elif isinstance(value, datetime.date):
            type_ = "DATE"
        else:
            type_ = "STRING"
    return bigquery.ScalarQueryParameter(name, type_, value)
