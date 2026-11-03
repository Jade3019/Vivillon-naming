"""Single place that decides where the bot's JSON files live (default: data/)."""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent / "data"))


def data_path(name: str) -> Path:
    return DATA_DIR / name
