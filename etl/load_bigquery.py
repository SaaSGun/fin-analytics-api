"""
Loads cleaned parquet files from data/processed/ into BigQuery.

Creates the dataset if it doesn't exist and loads each table with
WRITE_TRUNCATE (this is a batch/demo pipeline, not an incremental one).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

load_dotenv()

PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "fin-analytics-api")
DATASET = os.environ.get("BQ_DATASET", "fin_analytics")
LOCATION = os.environ.get("BQ_LOCATION", "US")

TABLES = {
    "security_master": "ticker",
    "market_prices": None,
    "fundamentals": "ticker",
    "esg_scores": "ticker",
    "portfolios": "portfolio_id",
    "portfolio_holdings": None,
    "benchmark_weights": None,
}


def ensure_dataset(client: bigquery.Client) -> None:
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET)
    try:
        client.get_dataset(dataset_ref)
    except NotFound:
        ds = bigquery.Dataset(dataset_ref)
        ds.location = LOCATION
        client.create_dataset(ds)
        print(f"created dataset {PROJECT_ID}.{DATASET}")


def load_table(client: bigquery.Client, table_name: str) -> None:
    path = PROCESSED_DIR / f"{table_name}.parquet"
    if not path.exists():
        print(f"skip {table_name}: {path} not found")
        return

    table_id = f"{PROJECT_ID}.{DATASET}.{table_name}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    with open(path, "rb") as f:
        job = client.load_table_from_file(f, table_id, job_config=job_config)
    job.result()
    table = client.get_table(table_id)
    print(f"loaded {table_name}: {table.num_rows} rows -> {table_id}")


def main() -> None:
    client = bigquery.Client(project=PROJECT_ID)
    ensure_dataset(client)
    for table_name in TABLES:
        load_table(client, table_name)


if __name__ == "__main__":
    main()
