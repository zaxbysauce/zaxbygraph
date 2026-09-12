from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path

SCHEMA_NAME = "schema.sql"
SCHEMA_VERSION = "1"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def connect_readonly_query(db_path: Path) -> sqlite3.Connection:
    """Separate connection for the sql command: query_only, no extensions."""
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        conn.enable_load_extension(False)
    except AttributeError:
        pass
    except sqlite3.OperationalError:
        pass
    return conn


def _schema_sql() -> str:
    return files("zaxbygraph").joinpath(SCHEMA_NAME).read_text(encoding="utf-8")


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_schema_sql())
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    conn.commit()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])
