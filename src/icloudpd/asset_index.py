"""Sharded on-disk index mapping asset_id to file paths.

Structure:
    .index/
      0E/
        0E454CB9-42BC-413B-8BB2-4A20F4BE1.json
      A3/
        A3C193B4-35E3-47DF-B1A2-9345A72B0E29.json

Each JSON file:
    {"paths": ["2022/03/15/IMG_1234.JPG"], "smart_albums": ["Favorites"]}
"""

import contextlib
import json
import logging
import os
import tempfile
from typing import Any, Dict, List

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


def load_asset_entry_full(directory: str, asset_id: str) -> Dict[str, Any] | None:
    """Load the full index entry including smart_albums."""
    path = index_entry_path(directory, asset_id)
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict) and "paths" in data:
            return data
        return None
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def save_asset_entry(
    directory: str,
    asset_id: str,
    paths: List[str],
    dry_run: bool,
    smart_albums: List[str] | None = None,
) -> None:
    if dry_run:
        return
    path = index_entry_path(directory, asset_id)
    entry_dir = os.path.dirname(path)
    entry: Dict[str, Any] = {"paths": paths}
    if smart_albums is not None:
        entry["smart_albums"] = smart_albums
    try:
        os.makedirs(entry_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=entry_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(entry, f)
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
    full_entry = load_asset_entry_full(directory, asset_id)
    if full_entry is None:
        full_entry = {"paths": []}
    paths = full_entry.get("paths", [])
    if path not in paths:
        paths.append(path)
    save_asset_entry(
        directory,
        asset_id,
        paths,
        dry_run=False,
        smart_albums=full_entry.get("smart_albums"),
    )


def update_smart_albums(
    directory: str, asset_id: str, smart_albums: List[str], dry_run: bool
) -> None:
    """Update the smart_albums field for an existing index entry."""
    if dry_run:
        return
    full_entry = load_asset_entry_full(directory, asset_id)
    if full_entry is None:
        return
    full_entry["smart_albums"] = smart_albums
    save_asset_entry(
        directory,
        asset_id,
        full_entry.get("paths", []),
        dry_run=False,
        smart_albums=smart_albums,
    )


def iter_all_asset_ids(directory: str) -> List[str]:
    """Return all asset IDs present in the index."""
    index_dir = os.path.join(directory, INDEX_DIR)
    result: List[str] = []
    if not os.path.isdir(index_dir):
        return result
    for shard in os.listdir(index_dir):
        shard_dir = os.path.join(index_dir, shard)
        if not os.path.isdir(shard_dir):
            continue
        for fname in os.listdir(shard_dir):
            if fname.endswith(".json"):
                result.append(fname[:-5])
    return result


def remove_asset_entry(directory: str, asset_id: str) -> None:
    path = index_entry_path(directory, asset_id)
    with contextlib.suppress(OSError):
        os.unlink(path)
