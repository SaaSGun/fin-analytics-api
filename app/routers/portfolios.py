from datetime import date

from fastapi import APIRouter, Depends, Query

from app.auth import require_scopes
from app.bigquery_client import dataset_ref, run_query, scalar_param
from app.deps import get_portfolio_meta
from app.models.schemas import (
    Envelope,
    HoldingRow,
    Meta,
    Pagination,
    PerformancePoint,
    PortfolioSummary,
    SectorExposure,
)
from app.pagination import (
    cursor_date,
    cursor_query,
    decode_cursor,
    limit_query,
    paginate,
)

router = APIRouter(
    prefix="/portfolios", tags=["portfolios"], dependencies=[Depends(require_scopes("confidential:read"))]
)


@router.get("", response_model=Envelope[list[PortfolioSummary]], summary="List all portfolios")
def list_portfolios(cursor: str | None = cursor_query(), limit: int = limit_query()):
    decoded = decode_cursor(cursor)
    after_id = decoded["portfolio_id"] if decoded else None

    sql = f"""
        SELECT portfolio_id, portfolio_name, strategy, aum_usd, cash_weight, benchmark_id, as_of_date
        FROM `{dataset_ref()}.portfolios`
        WHERE (@after_id IS NULL OR portfolio_id > @after_id)
        ORDER BY portfolio_id
        LIMIT {limit + 1}
    """
    df = run_query(sql, params=[scalar_param("after_id", after_id, "STRING")])
    rows = df.to_dict(orient="records")
    page, next_cursor, has_more = paginate(rows, limit, ("portfolio_id",))
    return Envelope(
        data=[PortfolioSummary(**r) for r in page],
        meta=Meta(pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=has_more)),
    )


@router.get("/{portfolio_id}/holdings", response_model=Envelope[list[HoldingRow]], summary="Current holdings")
def get_holdings(portfolio_id: str, cursor: str | None = cursor_query(), limit: int = limit_query()):
    get_portfolio_meta(portfolio_id)  # 404s if unknown
    decoded = decode_cursor(cursor)
    after_weight = decoded["weight"] if decoded else None
    after_ticker = decoded["ticker"] if decoded else None

    sql = f"""
        SELECT h.ticker, sm.company_name, sm.gics_sector, h.weight, h.shares, h.market_value
        FROM `{dataset_ref()}.portfolio_holdings` h
        JOIN `{dataset_ref()}.security_master` sm USING (ticker)
        WHERE h.portfolio_id = @portfolio_id
          AND (
            @after_weight IS NULL
            OR h.weight < @after_weight
            OR (h.weight = @after_weight AND h.ticker > @after_ticker)
          )
        ORDER BY h.weight DESC, h.ticker ASC
        LIMIT {limit + 1}
    """
    params = [
        scalar_param("portfolio_id", portfolio_id),
        scalar_param("after_weight", after_weight, "FLOAT64"),
        scalar_param("after_ticker", after_ticker, "STRING"),
    ]
    df = run_query(sql, params=params)
    rows = df.to_dict(orient="records")
    page, next_cursor, has_more = paginate(rows, limit, ("weight", "ticker"))
    return Envelope(
        data=[HoldingRow(**r) for r in page],
        meta=Meta(pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=has_more)),
    )


@router.get(
    "/{portfolio_id}/exposures",
    response_model=Envelope[list[SectorExposure]],
    summary="Sector active weight vs. benchmark",
)
def get_sector_exposures(portfolio_id: str, cursor: str | None = cursor_query(), limit: int = limit_query()):
    meta = get_portfolio_meta(portfolio_id)
    decoded = decode_cursor(cursor)
    after_active = decoded["active_weight"] if decoded else None
    after_sector = decoded["gics_sector"] if decoded else None

    sql = f"""
        WITH port AS (
          SELECT sm.gics_sector, SUM(h.weight) AS weight
          FROM `{dataset_ref()}.portfolio_holdings` h
          JOIN `{dataset_ref()}.security_master` sm USING (ticker)
          WHERE h.portfolio_id = @portfolio_id
          GROUP BY sm.gics_sector
        ),
        bench AS (
          SELECT sm.gics_sector, SUM(b.weight) AS weight
          FROM `{dataset_ref()}.benchmark_weights` b
          JOIN `{dataset_ref()}.security_master` sm USING (ticker)
          WHERE b.benchmark_id = @benchmark_id
          GROUP BY sm.gics_sector
        ),
        combined AS (
          SELECT
            COALESCE(port.gics_sector, bench.gics_sector) AS gics_sector,
            COALESCE(port.weight, 0) AS portfolio_weight,
            COALESCE(bench.weight, 0) AS benchmark_weight,
            COALESCE(port.weight, 0) - COALESCE(bench.weight, 0) AS active_weight
          FROM port FULL OUTER JOIN bench USING (gics_sector)
        )
        SELECT * FROM combined
        WHERE (
          @after_active IS NULL
          OR active_weight < @after_active
          OR (active_weight = @after_active AND gics_sector > @after_sector)
        )
        ORDER BY active_weight DESC, gics_sector ASC
        LIMIT {limit + 1}
    """
    params = [
        scalar_param("portfolio_id", portfolio_id),
        scalar_param("benchmark_id", meta["benchmark_id"]),
        scalar_param("after_active", after_active, "FLOAT64"),
        scalar_param("after_sector", after_sector, "STRING"),
    ]
    df = run_query(sql, params=params)
    rows = df.to_dict(orient="records")
    page, next_cursor, has_more = paginate(rows, limit, ("active_weight", "gics_sector"))
    return Envelope(
        data=[SectorExposure(**r) for r in page],
        meta=Meta(pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=has_more)),
    )


@router.get(
    "/{portfolio_id}/performance",
    response_model=Envelope[list[PerformancePoint]],
    summary="Cumulative return vs. benchmark (static current-weight approximation)",
)
def get_performance(
    portfolio_id: str,
    start: date | None = Query(None, description="inclusive start date; defaults to earliest available"),
    end: date | None = Query(None, description="inclusive end date; defaults to latest available"),
    cursor: str | None = cursor_query(),
    limit: int = limit_query(),
):
    """
    Approximates performance by holding today's portfolio/benchmark weights constant
    over the requested lookback window and compounding daily security returns. This is
    a simplification for demo purposes (no historical weight drift / rebalancing is
    modelled) and should not be treated as an audited performance return.
    """
    meta = get_portfolio_meta(portfolio_id)
    decoded = decode_cursor(cursor)
    after = cursor_date(decoded, "trade_date")

    sql = f"""
        WITH daily_returns AS (
          -- 7-day buffer before @start so the first requested day's LAG still
          -- resolves to the correct prior trading day (handles weekends/holidays);
          -- LAG never looks forward, so trade_date <= @end is an exact bound.
          SELECT ticker, trade_date,
                 close / LAG(close) OVER (PARTITION BY ticker ORDER BY trade_date) - 1 AS ret
          FROM `{dataset_ref()}.market_prices`
          WHERE (@start IS NULL OR trade_date >= DATE_SUB(@start, INTERVAL 7 DAY))
            AND (@end IS NULL OR trade_date <= @end)
        ),
        port_ret AS (
          SELECT dr.trade_date, SUM(dr.ret * h.weight) AS ret
          FROM daily_returns dr
          JOIN `{dataset_ref()}.portfolio_holdings` h
            ON h.ticker = dr.ticker AND h.portfolio_id = @portfolio_id
          WHERE dr.ret IS NOT NULL
            AND (@start IS NULL OR dr.trade_date >= @start)
            AND (@end IS NULL OR dr.trade_date <= @end)
          GROUP BY dr.trade_date
        ),
        bench_ret AS (
          SELECT dr.trade_date, SUM(dr.ret * b.weight) AS ret
          FROM daily_returns dr
          JOIN `{dataset_ref()}.benchmark_weights` b
            ON b.ticker = dr.ticker AND b.benchmark_id = @benchmark_id
          WHERE dr.ret IS NOT NULL
            AND (@start IS NULL OR dr.trade_date >= @start)
            AND (@end IS NULL OR dr.trade_date <= @end)
          GROUP BY dr.trade_date
        ),
        combined AS (
          SELECT
            p.trade_date,
            EXP(SUM(LN(1 + p.ret)) OVER (ORDER BY p.trade_date)) - 1 AS portfolio_cum_return,
            EXP(SUM(LN(1 + b.ret)) OVER (ORDER BY p.trade_date)) - 1 AS benchmark_cum_return
          FROM port_ret p
          JOIN bench_ret b USING (trade_date)
        )
        SELECT * FROM combined
        WHERE (@after IS NULL OR trade_date > @after)
        ORDER BY trade_date
        LIMIT {limit + 1}
    """
    params = [
        scalar_param("portfolio_id", portfolio_id),
        scalar_param("benchmark_id", meta["benchmark_id"]),
        scalar_param("start", start, "DATE"),
        scalar_param("end", end, "DATE"),
        scalar_param("after", after, "DATE"),
    ]
    df = run_query(sql, params=params)
    rows = df.to_dict(orient="records")
    page, next_cursor, has_more = paginate(rows, limit, ("trade_date",))
    return Envelope(
        data=[PerformancePoint(**r) for r in page],
        meta=Meta(pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=has_more)),
    )
