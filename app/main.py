from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.api_core.exceptions import RetryError

from app.bigquery_client import get_client
from app.observability import request_logging_middleware, setup_logging
from app.routers import benchmarks, esg, portfolios, securities

setup_logging()

app = FastAPI(
    title="Fin Analytics API",
    description=(
        "Analytics API over a BigQuery warehouse of security reference data, market "
        "prices, fundamentals, ESG risk scores, and model-portfolio holdings, built "
        "for portfolio manager and ESG team workflows."
    ),
    version="0.1.0",
)

# Callers are backend/service clients (not browser JS), authenticated via
# a per-route X-API-Key scope check (see app/auth.py) rather than CORS, so
# permissive CORS here is harmless - it only governs browser JS access.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.middleware("http")(request_logging_middleware)

@app.exception_handler(RetryError)
async def bigquery_retries_exhausted(request: Request, exc: RetryError):
    # Raised when run_query's capped BigQuery retries run out - in practice
    # BigQuery's API rate limit under heavy load. Transient, so 503 +
    # Retry-After rather than a generic 500.
    return JSONResponse(
        status_code=503,
        content={"detail": "BigQuery is temporarily overloaded, retry shortly"},
        headers={"Retry-After": "5"},
    )


app.include_router(securities.router)
app.include_router(portfolios.router)
app.include_router(esg.router)
app.include_router(benchmarks.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/health/ready", tags=["meta"])
def health_ready():
    try:
        get_client().query("SELECT 1").result(timeout=5)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"BigQuery unreachable: {exc}") from exc
    return {"status": "ok"}
