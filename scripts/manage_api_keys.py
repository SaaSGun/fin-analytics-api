"""
Admin CLI for issuing/listing/revoking API keys for the Fin Analytics API.

Only the SHA-256 hash of a key is ever stored - the raw key is printed
once at creation time and cannot be retrieved again. Run this with
credentials that have write access to BigQuery (e.g. your own gcloud ADC
as project owner); the deployed API service itself only ever reads this
table.

Usage:
  python scripts/manage_api_keys.py create --client-name "dashboard-backend" --scopes standard:read,confidential:read
  python scripts/manage_api_keys.py list
  python scripts/manage_api_keys.py revoke --client-name "dashboard-backend"
"""
from __future__ import annotations

import argparse
import hashlib
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from app.config import get_settings

VALID_SCOPES = {"standard:read", "standard:write", "confidential:read", "confidential:write"}


def table_id() -> str:
    settings = get_settings()
    return f"{settings.gcp_project_id}.{settings.bq_dataset}.api_keys"


def ensure_table(client: bigquery.Client) -> None:
    try:
        client.get_table(table_id())
    except NotFound:
        schema = [
            bigquery.SchemaField("key_hash", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("client_name", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("scopes", "STRING", mode="REPEATED"),
            bigquery.SchemaField("active", "BOOL", mode="REQUIRED"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
        ]
        client.create_table(bigquery.Table(table_id(), schema=schema))
        print(f"created table {table_id()}")


def cmd_create(args: argparse.Namespace) -> None:
    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    invalid = set(scopes) - VALID_SCOPES
    if invalid:
        raise SystemExit(f"invalid scopes: {sorted(invalid)}. valid: {sorted(VALID_SCOPES)}")

    raw_key = f"bwfin_{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    client = bigquery.Client(project=get_settings().gcp_project_id)
    ensure_table(client)
    # DML INSERT, not the streaming insert API: streamed rows sit in a
    # buffer that UPDATE/DELETE can't target for up to 90 minutes, which
    # would make an immediate `revoke` after `create` silently no-op.
    client.query(
        f"""
        INSERT INTO `{table_id()}` (key_hash, client_name, scopes, active, created_at)
        VALUES (@key_hash, @client_name, @scopes, TRUE, CURRENT_TIMESTAMP())
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("key_hash", "STRING", key_hash),
                bigquery.ScalarQueryParameter("client_name", "STRING", args.client_name),
                bigquery.ArrayQueryParameter("scopes", "STRING", scopes),
            ]
        ),
    ).result()

    print("API key created - copy it now, it will not be shown again:")
    print(raw_key)
    print(f"client: {args.client_name}  scopes: {scopes}")


def cmd_list(args: argparse.Namespace) -> None:
    client = bigquery.Client(project=get_settings().gcp_project_id)
    ensure_table(client)
    rows = client.query(
        f"SELECT client_name, scopes, active, created_at FROM `{table_id()}` ORDER BY created_at DESC"
    ).result()
    for row in rows:
        print(f"{row.client_name:<30} active={row.active}  scopes={row.scopes}  created_at={row.created_at}")


def cmd_revoke(args: argparse.Namespace) -> None:
    client = bigquery.Client(project=get_settings().gcp_project_id)
    client.query(
        f"UPDATE `{table_id()}` SET active = FALSE WHERE client_name = @client_name",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("client_name", "STRING", args.client_name)]
        ),
    ).result()
    print(f"revoked all keys for client '{args.client_name}' (takes up to 5 min to take effect on warm instances)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="issue a new API key")
    p_create.add_argument("--client-name", required=True)
    p_create.add_argument("--scopes", required=True, help="comma-separated, e.g. standard:read,confidential:read")
    p_create.set_defaults(func=cmd_create)

    p_list = sub.add_parser("list", help="list all key records (hashes are never shown)")
    p_list.set_defaults(func=cmd_list)

    p_revoke = sub.add_parser("revoke", help="deactivate all keys for a client")
    p_revoke.add_argument("--client-name", required=True)
    p_revoke.set_defaults(func=cmd_revoke)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
