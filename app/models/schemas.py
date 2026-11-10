from datetime import date
from typing import Generic, TypeVar

from pydantic import BaseModel, Field


class SecurityProfile(BaseModel):
    ticker: str
    company_name: str
    gics_sector: str | None = None
    gics_sub_industry: str | None = None
    hq_state: str | None = None
    market_cap: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    dividend_yield: float | None = None
    beta: float | None = None
    last_close: float | None = None
    last_trade_date: date | None = None
    total_esg_risk_score: float | None = None
    environment_risk_score: float | None = None
    social_risk_score: float | None = None
    governance_risk_score: float | None = None
    esg_risk_category: str | None = None
    esg_source: str | None = None


class PricePoint(BaseModel):
    trade_date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None


class PortfolioSummary(BaseModel):
    portfolio_id: str
    portfolio_name: str
    strategy: str
    aum_usd: float
    cash_weight: float
    benchmark_id: str
    as_of_date: date


class HoldingRow(BaseModel):
    ticker: str
    company_name: str | None = None
    gics_sector: str | None = None
    weight: float
    shares: float | None = None
    market_value: float | None = None


class SectorExposure(BaseModel):
    gics_sector: str
    portfolio_weight: float
    benchmark_weight: float
    active_weight: float


class PerformancePoint(BaseModel):
    trade_date: date
    portfolio_cum_return: float
    benchmark_cum_return: float


class ESGPortfolioSummary(BaseModel):
    portfolio_id: str
    portfolio_weighted_esg_risk_score: float
    benchmark_weighted_esg_risk_score: float
    portfolio_weighted_environment_score: float | None = None
    portfolio_weighted_social_score: float | None = None
    portfolio_weighted_governance_score: float | None = None
    risk_category_weights: dict[str, float]


class ESGLaggard(BaseModel):
    ticker: str
    company_name: str | None = None
    gics_sector: str | None = None
    weight: float
    total_esg_risk_score: float
    risk_category: str
    weighted_risk_contribution: float


class ScreenResult(BaseModel):
    ticker: str
    company_name: str
    gics_sector: str | None = None
    market_cap: float | None = None
    total_esg_risk_score: float | None = None
    risk_category: str | None = None


class BenchmarkConstituent(BaseModel):
    ticker: str
    company_name: str | None = None
    gics_sector: str | None = None
    weight: float


class Pagination(BaseModel):
    next_cursor: str | None = None
    limit: int
    has_more: bool


class Meta(BaseModel):
    pagination: Pagination | None = None


T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    """Every endpoint returns this shape - `data` is a single object for
    singleton resources or a list for collections, and `meta.pagination`
    is populated only for paginated list endpoints - so clients parse
    every response the same way."""

    data: T
    meta: Meta = Field(default_factory=Meta)
