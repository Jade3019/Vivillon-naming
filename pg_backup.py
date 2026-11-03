"""Back up and restore shiny hunts / collections.

  python pg_backup.py backup [DIR]    JSON files or Postgres -> DIR/*.json
  python pg_backup.py restore [DIR]   DIR/*.json -> Postgres (DATABASE_URL required)

backup reads from PostgreSQL when DATABASE_URL is set, otherwise from the
bot's JSON files (SHINYHUNTS_FILE / COLLECTIONS_FILE).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pg_store
from data_paths import data_path

SOURCES = {
    "shiny_hunts": ("SHINYHUNTS_FILE", str(data_path("shinyhunts.json"))),
    "collections": ("COLLECTIONS_FILE", str(data_path("collections.json"))),
}


def json_path(table: str) -> Path:
    env, default = SOURCES[table]
    return Path(os.environ.get(env, default))


def backup(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for table in SOURCES:
        target = directory / f"{table}.json"
        if pg_store.enabled():
            data = pg_store.load(table)
            target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        elif json_path(table).exists():
            shutil.copyfile(json_path(table), target)
        else:
            print(f"skip {table}: nothing to back up")
            continue
        print(f"backed up {table} -> {target}")


def restore(directory: Path) -> None:
    if not pg_store.enabled():
        sys.exit("DATABASE_URL is not set")
    for table in SOURCES:
        source = directory / f"{table}.json"
        if not source.exists():
            print(f"skip {table}: {source} not found")
            continue
        data = json.loads(source.read_text(encoding="utf-8"))
        pg_store.save(table, data)
        rows = sum(len(users) for users in data.values())
        print(f"restored {table}: {rows} rows")


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    default = f"backups/{datetime.now():%Y%m%d-%H%M%S}"
    directory = Path(sys.argv[2] if len(sys.argv) > 2 else default)
    if action == "backup":
        backup(directory)
    elif action == "restore":
        restore(directory)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
