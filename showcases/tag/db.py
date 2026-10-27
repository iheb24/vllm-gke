"""Build and locate the synthetic serving-analytics SQLite database.

The database is derived from data/schema.sql and data/seed.sql next to this
module. ensure_database() creates it on first use and is a no-op afterwards,
so local runs, tests, and container startup all share one code path. The
data is synthetic demo data, not real GCP billing or telemetry.
"""

import sqlite3
from pathlib import Path

MODULE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = MODULE_DIR / "data" / "schema.sql"
SEED_PATH = MODULE_DIR / "data" / "seed.sql"
DEFAULT_DB_PATH = MODULE_DIR / "data" / "serving.db"


def ensure_database(db_path=DEFAULT_DB_PATH):
    path = Path(db_path)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.executescript(SEED_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return path
