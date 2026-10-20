from contextlib import contextmanager
from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"

_pool: ConnectionPool | None = None


def _configure(conn: psycopg.Connection) -> None:
    register_vector(conn)
    conn.execute("SET statement_timeout = '5s'")
    conn.execute(f"SET hnsw.ef_search = {int(get_settings().hnsw_ef_search)}")
    conn.commit()


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_settings().database_url,
            min_size=2,
            max_size=max(2, get_settings().db_pool_max),
            kwargs={"row_factory": dict_row, "autocommit": True},
            configure=_configure,
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def connect(autocommit: bool = False):
    """Plain connection for batch jobs (no statement timeout)."""
    conn = psycopg.connect(get_settings().database_url, row_factory=dict_row, autocommit=autocommit)
    try:
        try:
            register_vector(conn)
        except psycopg.ProgrammingError:
            pass  # extension not created yet (first migration)
        yield conn
    finally:
        conn.close()


def migrate() -> None:
    # Every uvicorn worker runs this at startup; the advisory lock makes them take turns.
    with connect(autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(7240001)")
        try:
            for path in sorted(MIGRATIONS.glob("*.sql")):
                conn.execute(path.read_text(encoding="utf-8"))
        finally:
            conn.execute("SELECT pg_advisory_unlock(7240001)")


def get_meta(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = %s", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, value),
    )
