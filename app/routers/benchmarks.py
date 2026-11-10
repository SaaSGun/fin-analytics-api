from fastapi import APIRouter, Depends, HTTPException

from app.auth import require_scopes
from app.bigquery_client import dataset_ref, run_query, scalar_param
from app.models.schemas import BenchmarkConstituent, Envelope, Meta, Pagination
from app.pagination import cursor_query, decode_cursor, limit_query, paginate

router = APIRouter(
    prefix="/benchmarks", tags=["benchmarks"], dependencies=[Depends(require_scopes("standard:read"))]
)


@router.get(
    "/{benchmark_id}/constituents",
    response_model=Envelope[list[BenchmarkConstituent]],
    summary="Benchmark constituent weights",
)
def get_constituents(benchmark_id: str, cursor: str | None = cursor_query(), limit: int = limit_query()):
    decoded = decode_cursor(cursor)
    after_weight = decoded["weight"] if decoded else None
    after_ticker = decoded["ticker"] if decoded else None

    sql = f"""
        SELECT b.ticker, sm.company_name, sm.gics_sector, b.weight
        FROM `{dataset_ref()}.benchmark_weights` b
        JOIN `{dataset_ref()}.security_master` sm USING (ticker)
        WHERE b.benchmark_id = @benchmark_id
          AND (
            @after_weight IS NULL
            OR b.weight < @after_weight
            OR (b.weight = @after_weight AND b.ticker > @after_ticker)
          )
        ORDER BY b.weight DESC, b.ticker ASC
        LIMIT {limit + 1}
    """
    params = [
        scalar_param("benchmark_id", benchmark_id),
        scalar_param("after_weight", after_weight, "FLOAT64"),
        scalar_param("after_ticker", after_ticker, "STRING"),
    ]
    df = run_query(sql, params=params)
    rows = df.to_dict(orient="records")
    if not rows and cursor is None:
        raise HTTPException(status_code=404, detail=f"benchmark '{benchmark_id}' not found")

    page, next_cursor, has_more = paginate(rows, limit, ("weight", "ticker"))
    return Envelope(
        data=[BenchmarkConstituent(**r) for r in page],
        meta=Meta(pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=has_more)),
    )
