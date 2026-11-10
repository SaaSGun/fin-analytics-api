from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import require_scopes
from app.bigquery_client import dataset_ref, run_query, scalar_param
from app.models.schemas import Envelope, Meta, Pagination, PricePoint, SecurityProfile
from app.pagination import (
    cursor_date,
    cursor_query,
    decode_cursor,
    limit_query,
    paginate,
)

router = APIRouter(
    prefix="/securities", tags=["securities"], dependencies=[Depends(require_scopes("standard:read"))]
)


@router.get("/{ticker}", response_model=Envelope[SecurityProfile], summary="Security 360 profile")
def get_security(ticker: str):
    """Reference data + latest fundamentals + latest ESG + latest price for one security."""
    sql = f"""
        SELECT
          sm.ticker, sm.company_name, sm.gics_sector, sm.gics_sub_industry, sm.hq_state,
          f.market_cap, f.trailing_pe, f.forward_pe, f.dividend_yield, f.beta,
          p.close AS last_close, p.trade_date AS last_trade_date,
          e.total_esg_risk_score, e.environment_risk_score, e.social_risk_score, e.governance_risk_score,
          e.risk_category AS esg_risk_category, e.source AS esg_source
        FROM `{dataset_ref()}.security_master` sm
        LEFT JOIN `{dataset_ref()}.fundamentals` f USING (ticker)
        LEFT JOIN `{dataset_ref()}.esg_scores` e USING (ticker)
        LEFT JOIN (
          SELECT ticker, close, trade_date
          FROM `{dataset_ref()}.market_prices`
          WHERE ticker = @ticker
          QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY trade_date DESC) = 1
        ) p USING (ticker)
        WHERE sm.ticker = @ticker
    """
    df = run_query(sql, params=[scalar_param("ticker", ticker.upper())])
    if df.empty:
        raise HTTPException(status_code=404, detail=f"ticker '{ticker}' not found")
    return Envelope(data=SecurityProfile(**df.iloc[0].to_dict()))


@router.get("/{ticker}/prices", response_model=Envelope[list[PricePoint]], summary="Historical daily OHLCV")
def get_prices(
    ticker: str,
    start: date | None = Query(None, description="inclusive start date"),
    end: date | None = Query(None, description="inclusive end date"),
    cursor: str | None = cursor_query(),
    limit: int = limit_query(),
):
    decoded = decode_cursor(cursor)
    after = cursor_date(decoded, "trade_date")

    sql = f"""
        SELECT trade_date, open, high, low, close, volume
        FROM `{dataset_ref()}.market_prices`
        WHERE ticker = @ticker
          AND (@start IS NULL OR trade_date >= @start)
          AND (@end IS NULL OR trade_date <= @end)
          AND (@after IS NULL OR trade_date > @after)
        ORDER BY trade_date
        LIMIT {limit + 1}
    """
    params = [
        scalar_param("ticker", ticker.upper()),
        scalar_param("start", start, "DATE"),
        scalar_param("end", end, "DATE"),
        scalar_param("after", after, "DATE"),
    ]
    df = run_query(sql, params=params)
    rows = df.to_dict(orient="records")
    if not rows and cursor is None:
        raise HTTPException(status_code=404, detail=f"no price history for '{ticker}'")

    page, next_cursor, has_more = paginate(rows, limit, ("trade_date",))
    return Envelope(
        data=[PricePoint(**r) for r in page],
        meta=Meta(pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=has_more)),
    )
