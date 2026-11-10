"""
Export the live FastAPI OpenAPI schema to docs/openapi.yaml.

This is a code-first project: the API contract is generated from the
FastAPI routes/Pydantic models, not hand-authored first. This script just
snapshots that generated contract into a committed file so it can be
reviewed, diffed, or fed into other tooling (client codegen, API
gateways, etc.) without running the server.

Usage: python scripts/export_openapi.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import yaml

from app.main import app

OUT_PATH = REPO_ROOT / "docs" / "openapi.yaml"


def main() -> None:
    schema = app.openapi()
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(schema, f, sort_keys=False, default_flow_style=False, allow_unicode=True)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
