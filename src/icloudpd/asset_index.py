"""Sharded on-disk index mapping asset_id to file paths.

Structure:
    .index/
      0E/
        0E454CB9-42BC-413B-8BB2-4A20F4BE1.json
      A3/
        A3C193B4-35E3-47DF-B1A2-9345A72B0E29.json

Each JSON file:
    {"paths": ["2022/03/15/IMG_1234.JPG"]}
"""

import contextlib
import json
import logging
import os
import tempfile
from typing import List

logger = logging.getLogger(__name__)

INDEX_DIR = ".index"


def index_entry_path(directory: str, asset_id: str) -> str:
    shard = asset_id[:2].upper()
    return os.path.join(directory, INDEX_DIR, shard, f"{asset_id}.json")


def load_asset_entry(directory: str, asset_id: str) -> List[str] | None:
    path = index_entry_path(directory, asset_id)
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict) and "paths" in data:
            return data["paths"]
        return None
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def save_asset_entry(directory: str, asset_id: str, paths: List[str], dry_run: bool) -> None:
    if dry_run:
        return
    path = index_entry_path(directory, asset_id)
    entry_dir = os.path.dirname(path)
    try:
        os.makedirs(entry_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=entry_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"paths": paths}, f)
            os.replace(tmp_path, path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
    except Exception:
        logger.warning("Failed to save asset index entry for %s", asset_id, exc_info=True)


def add_asset_path(directory: str, asset_id: str, path: str, dry_run: bool) -> None:
    if dry_run:
        return
    existing = load_asset_entry(directory, asset_id)
    if existing is None:
        existing = []
    if path not in existing:
        existing.append(path)
    save_asset_entry(directory, asset_id, existing, dry_run=False)


def remove_asset_entry(directory: str, asset_id: str) -> None:
    path = index_entry_path(directory, asset_id)
    with contextlib.suppress(OSError):
        os.unlink(path)
