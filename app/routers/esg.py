from fastapi import APIRouter, Depends, Query

from app.auth import require_scopes
from app.bigquery_client import dataset_ref, run_query, scalar_param
from app.deps import get_portfolio_meta
from app.models.schemas import (
    Envelope,
    ESGLaggard,
    ESGPortfolioSummary,
    Meta,
    Pagination,
    ScreenResult,
)
from app.pagination import cursor_query, decode_cursor, limit_query, paginate

router = APIRouter(tags=["esg"])


@router.get(
    "/portfolios/{portfolio_id}/esg-summary",
    response_model=Envelope[ESGPortfolioSummary],
    summary="Weighted ESG risk profile vs. benchmark",
    dependencies=[Depends(require_scopes("confidential:read"))],
)
def get_esg_summary(portfolio_id: str):
    meta = get_portfolio_meta(portfolio_id)

    agg_sql = f"""
        WITH port AS (
          SELECT
            SUM(h.weight * e.total_esg_risk_score) AS port_total,
            SUM(h.weight * e.environment_risk_score) AS port_env,
            SUM(h.weight * e.social_risk_score) AS port_soc,
            SUM(h.weight * e.governance_risk_score) AS port_gov
          FROM `{dataset_ref()}.portfolio_holdings` h
          JOIN `{dataset_ref()}.esg_scores` e USING (ticker)
          WHERE h.portfolio_id = @portfolio_id
        ),
        bench AS (
          SELECT SUM(b.weight * e.total_esg_risk_score) AS bench_total
          FROM `{dataset_ref()}.benchmark_weights` b
          JOIN `{dataset_ref()}.esg_scores` e USING (ticker)
          WHERE b.benchmark_id = @benchmark_id
        )
        SELECT * FROM port, bench
    """
    dist_sql = f"""
        SELECT e.risk_category, SUM(h.weight) AS weight
        FROM `{dataset_ref()}.portfolio_holdings` h
        JOIN `{dataset_ref()}.esg_scores` e USING (ticker)
        WHERE h.portfolio_id = @portfolio_id
        GROUP BY e.risk_category
    """
    params = [
        scalar_param("portfolio_id", portfolio_id),
        scalar_param("benchmark_id", meta["benchmark_id"]),
    ]
    agg = run_query(agg_sql, params=params).iloc[0]
    dist = run_query(dist_sql, params=[scalar_param("portfolio_id", portfolio_id)])

    return Envelope(
        data=ESGPortfolioSummary(
            portfolio_id=portfolio_id,
            portfolio_weighted_esg_risk_score=agg["port_total"],
            benchmark_weighted_esg_risk_score=agg["bench_total"],
            portfolio_weighted_environment_score=agg["port_env"],
            portfolio_weighted_social_score=agg["port_soc"],
            portfolio_weighted_governance_score=agg["port_gov"],
            risk_category_weights=dict(zip(dist["risk_category"], dist["weight"])),
        )
    )


@router.get(
    "/portfolios/{portfolio_id}/esg-laggards",
    response_model=Envelope[list[ESGLaggard]],
    summary="Largest weighted ESG risk contributors in a portfolio",
    dependencies=[Depends(require_scopes("confidential:read"))],
)
def get_esg_laggards(
    portfolio_id: str,
    cursor: str | None = cursor_query(),
    limit: int = limit_query(default=10, max_limit=100),
):
    get_portfolio_meta(portfolio_id)
    decoded = decode_cursor(cursor)
    after_contrib = decoded["weighted_risk_contribution"] if decoded else None
    after_ticker = decoded["ticker"] if decoded else None

    sql = f"""
        SELECT
          h.ticker, sm.company_name, sm.gics_sector, h.weight,
          e.total_esg_risk_score, e.risk_category,
          h.weight * e.total_esg_risk_score AS weighted_risk_contribution
        FROM `{dataset_ref()}.portfolio_holdings` h
        JOIN `{dataset_ref()}.esg_scores` e USING (ticker)
        JOIN `{dataset_ref()}.security_master` sm USING (ticker)
        WHERE h.portfolio_id = @portfolio_id
          AND (
            @after_contrib IS NULL
            OR (h.weight * e.total_esg_risk_score) < @after_contrib
            OR ((h.weight * e.total_esg_risk_score) = @after_contrib AND h.ticker > @after_ticker)
          )
        ORDER BY weighted_risk_contribution DESC, h.ticker ASC
        LIMIT {limit + 1}
    """
    params = [
        scalar_param("portfolio_id", portfolio_id),
        scalar_param("after_contrib", after_contrib, "FLOAT64"),
        scalar_param("after_ticker", after_ticker, "STRING"),
    ]
    df = run_query(sql, params=params)
    rows = df.to_dict(orient="records")
    page, next_cursor, has_more = paginate(rows, limit, ("weighted_risk_contribution", "ticker"))
    return Envelope(
        data=[ESGLaggard(**r) for r in page],
        meta=Meta(pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=has_more)),
    )


@router.get(
    "/esg/screen",
    response_model=Envelope[list[ScreenResult]],
    summary="Screen the universe by sector / ESG risk / market cap",
    dependencies=[Depends(require_scopes("standard:read"))],
)
def screen_securities(
    sector: str | None = None,
    max_risk_score: float | None = Query(None, description="max total ESG risk score (lower = less risky)"),
    min_market_cap: float | None = None,
    cursor: str | None = cursor_query(),
    limit: int = limit_query(),
):
    decoded = decode_cursor(cursor)
    after_score = decoded["total_esg_risk_score"] if decoded else None
    after_ticker = decoded["ticker"] if decoded else None

    sql = f"""
        SELECT sm.ticker, sm.company_name, sm.gics_sector, f.market_cap,
               e.total_esg_risk_score, e.risk_category
        FROM `{dataset_ref()}.security_master` sm
        JOIN `{dataset_ref()}.fundamentals` f USING (ticker)
        JOIN `{dataset_ref()}.esg_scores` e USING (ticker)
        WHERE (@sector IS NULL OR sm.gics_sector = @sector)
          AND (@max_risk_score IS NULL OR e.total_esg_risk_score <= @max_risk_score)
          AND (@min_market_cap IS NULL OR f.market_cap >= @min_market_cap)
          AND (
            @after_score IS NULL
            OR e.total_esg_risk_score > @after_score
            OR (e.total_esg_risk_score = @after_score AND sm.ticker > @after_ticker)
          )
        ORDER BY e.total_esg_risk_score ASC, sm.ticker ASC
        LIMIT {limit + 1}
    """
    params = [
        scalar_param("sector", sector),
        scalar_param("max_risk_score", max_risk_score, "FLOAT64"),
        scalar_param("min_market_cap", min_market_cap, "FLOAT64"),
        scalar_param("after_score", after_score, "FLOAT64"),
        scalar_param("after_ticker", after_ticker, "STRING"),
    ]
    df = run_query(sql, params=params)
    rows = df.to_dict(orient="records")
    page, next_cursor, has_more = paginate(rows, limit, ("total_esg_risk_score", "ticker"))
    return Envelope(
        data=[ScreenResult(**r) for r in page],
        meta=Meta(pagination=Pagination(next_cursor=next_cursor, limit=limit, has_more=has_more)),
    )
