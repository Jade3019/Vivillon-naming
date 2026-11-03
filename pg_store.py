"""Optional PostgreSQL storage for shiny hunts and user collections.

Enabled when the DATABASE_URL environment variable is set. When it is not set,
the bot keeps using its JSON files, so nothing changes for existing setups.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

TABLES = {"shiny_hunts", "collections"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS shiny_hunts (
    pokemon_key TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    PRIMARY KEY (pokemon_key, user_id)
);
CREATE INDEX IF NOT EXISTS shiny_hunts_user_idx ON shiny_hunts (user_id);
CREATE TABLE IF NOT EXISTS collections (
    pokemon_key TEXT NOT NULL,
    user_id BIGINT NOT NULL,
    PRIMARY KEY (pokemon_key, user_id)
);
CREATE INDEX IF NOT EXISTS collections_user_idx ON collections (user_id);
CREATE TABLE IF NOT EXISTS storage_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_lock = threading.RLock()
_conn = None
_registered: dict[Path, str] = {}


def enabled() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def register(path: Path, table: str) -> None:
    """Route load/save calls for a JSON path to a Postgres table."""
    if table not in TABLES:
        raise ValueError(f"Unknown table {table}")
    _registered[Path(path).resolve()] = table
    if enabled():
        with _lock:
            _import_json_once(table, Path(path))


def table_for(path: Path) -> str | None:
    if not enabled():
        return None
    return _registered.get(Path(path).resolve())


def _connect():
    global _conn
    import psycopg

    if _conn is None or _conn.closed:
        _conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=False)
        _conn.execute(SCHEMA)
        _conn.commit()
    return _conn


def _run(fn):
    """Run fn(conn), reconnecting once if the connection was dropped."""
    import psycopg

    global _conn
    with _lock:
        for attempt in (1, 2):
            try:
                conn = _connect()
                result = fn(conn)
                conn.commit()
                return result
            except psycopg.OperationalError:
                try:
                    if _conn is not None:
                        _conn.close()
                except Exception:
                    pass
                _conn = None
                if attempt == 2:
                    raise
            except Exception:
                if _conn is not None and not _conn.closed:
                    _conn.rollback()
                raise


def load(table: str) -> dict[str, list[int]]:
    def work(conn):
        rows = conn.execute(
            f"SELECT pokemon_key, user_id FROM {table} ORDER BY pokemon_key, user_id"
        ).fetchall()
        data: dict[str, list[int]] = {}
        for key, user_id in rows:
            data.setdefault(key, []).append(user_id)
        return data

    try:
        return _run(work)
    except Exception as error:
        raise ValueError(f"Could not read {table} from PostgreSQL") from error


def save(table: str, data: dict[str, list[int]]) -> None:
    wanted = {(key, int(uid)) for key, uids in data.items() for uid in uids}

    def work(conn):
        existing = set(
            conn.execute(f"SELECT pokemon_key, user_id FROM {table}").fetchall()
        )
        stale = existing - wanted
        fresh = wanted - existing
        with conn.cursor() as cur:
            if stale:
                cur.executemany(
                    f"DELETE FROM {table} WHERE pokemon_key = %s AND user_id = %s",
                    list(stale),
                )
            if fresh:
                cur.executemany(
                    f"INSERT INTO {table} (pokemon_key, user_id) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    list(fresh),
                )

    try:
        _run(work)
    except Exception as error:
        raise ValueError(f"Could not save {table} to PostgreSQL") from error


def _import_json_once(table: str, path: Path) -> None:
    """Copy an existing JSON file into an empty table, one time only."""
    flag = f"imported_{table}"

    def work(conn):
        done = conn.execute(
            "SELECT 1 FROM storage_meta WHERE key = %s", (flag,)
        ).fetchone()
        if done:
            return 0
        count = 0
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            rows = [
                (key, int(uid)) for key, uids in data.items() for uid in uids
            ]
            with conn.cursor() as cur:
                cur.executemany(
                    f"INSERT INTO {table} (pokemon_key, user_id) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    rows,
                )
            count = len(rows)
        if path.exists():
            conn.execute(
                "INSERT INTO storage_meta (key, value) VALUES (%s, 'true') "
                "ON CONFLICT DO NOTHING",
                (flag,),
            )
        return count

    try:
        count = _run(work)
        if count:
            logger.info("Imported %d rows from %s into %s", count, path, table)
    except Exception:
        logger.exception("Could not import %s into PostgreSQL", path)
