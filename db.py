"""
Shared database connection module.
Reads DATABASE_URL from environment variable (Vercel) or config.yaml (local).
"""
import os
import yaml
import psycopg2
import psycopg2.extras
from pathlib import Path

BASE_DIR = Path(__file__).parent


def get_database_url() -> str:
    # Environment variable takes priority (used by Vercel)
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    # Fall back to config.yaml for local use
    config = yaml.safe_load((BASE_DIR / "config.yaml").read_text(encoding="utf-8"))
    return config["database_url"]


def get_conn():
    return psycopg2.connect(get_database_url())
