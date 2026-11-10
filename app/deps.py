from fastapi import HTTPException

from app.bigquery_client import dataset_ref, run_query, scalar_param


def get_portfolio_meta(portfolio_id: str) -> dict:
    sql = f"""
        SELECT portfolio_id, portfolio_name, strategy, aum_usd, cash_weight, benchmark_id, as_of_date
        FROM `{dataset_ref()}.portfolios`
        WHERE portfolio_id = @portfolio_id
    """
    df = run_query(sql, params=[scalar_param("portfolio_id", portfolio_id)])
    if df.empty:
        raise HTTPException(status_code=404, detail=f"portfolio '{portfolio_id}' not found")
    return df.iloc[0].to_dict()
