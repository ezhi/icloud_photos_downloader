"""Persist until-found watermark so interrupted runs don't leave gaps.

When --until-found is active and a run is interrupted (crash, cancel, etc.),
the next run must scan at least as far as the previous run reached before
allowing --until-found to trigger an early exit. This module persists that
"how far we got" state per album.
"""

import contextlib
import json
import logging
import os
import tempfile
from typing import Any, Dict

from icloudpd.album_cache import CACHE_DIR

logger = logging.getLogger(__name__)

WATERMARK_FILE = ".until_found_watermark.json"


def _watermark_path(directory: str) -> str:
    return os.path.join(directory, CACHE_DIR, WATERMARK_FILE)


def load_watermarks(directory: str) -> Dict[str, Any]:
    path = _watermark_path(directory)
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save_watermarks(directory: str, data: Dict[str, Any]) -> None:
    path = _watermark_path(directory)
    cache_dir = os.path.dirname(path)
    try:
        os.makedirs(cache_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
    except Exception:
        logger.warning("Failed to save watermark to %s", path, exc_info=True)


def get_watermark(directory: str, album_name: str) -> Dict[str, Any] | None:
    data = load_watermarks(directory)
    return data.get(album_name)


def save_watermark(
    directory: str,
    album_name: str,
    asset_date_ms: int,
    asset_id: str,
    completed: bool,
    dry_run: bool,
) -> None:
    if dry_run:
        return
    data = load_watermarks(directory)
    data[album_name] = {
        "asset_date_ms": asset_date_ms,
        "asset_id": asset_id,
        "completed": completed,
    }
    _save_watermarks(directory, data)
