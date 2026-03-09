"""Smart album (Favorites, Hidden) membership via CloudKit zone change tracking.

First sync: full fetch of Favorites + Hidden album asset IDs.
Subsequent syncs: incremental via records/changes endpoint.
Fallback: token expired → full refetch.
"""

import contextlib
import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Set, Tuple

from icloudpd.album_cache import (
    CACHE_DIR,
    AlbumMembershipResult,
    _load_album_cache,
    _save_album_cache,
)
from pyicloud_ipd.services.photos import PhotoLibrary

logger = logging.getLogger(__name__)

SMART_ALBUM_FIELDS: Dict[str, Tuple[str, int]] = {
    "Favorites": ("isFavorite", 1),
    "Hidden": ("isHidden", 1),
}

SYNC_STATE_FILE = ".sync_state.json"


def _sync_state_path(directory: str) -> str:
    return os.path.join(directory, CACHE_DIR, SYNC_STATE_FILE)


def _load_sync_state(directory: str) -> Dict[str, Any] | None:
    path = _sync_state_path(directory)
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _save_sync_state(directory: str, state: Dict[str, Any]) -> None:
    path = _sync_state_path(directory)
    cache_dir = os.path.dirname(path)
    try:
        os.makedirs(cache_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
    except Exception:
        logger.warning("Failed to save sync state to %s", path, exc_info=True)


def _initial_fetch(
    library: PhotoLibrary,
    directory: str,
    dry_run: bool,
) -> Tuple[Dict[str, Set[str]], Set[str]]:
    """Full fetch of Favorites + Hidden album membership. Returns (album_sets, changed_ids)."""
    albums_dict = library.albums
    album_sets: Dict[str, Set[str]] = {}
    changed_asset_ids: Set[str] = set()

    for album_name in SMART_ALBUM_FIELDS:
        album = albums_dict.get(album_name)
        if album is None:
            logger.debug("Smart album %s not found in library", album_name)
            album_sets[album_name] = set()
            continue

        asset_ids = album.fetch_asset_ids()
        new_set = set(asset_ids)
        album_sets[album_name] = new_set

        # Compare with existing cache to detect changes
        cached_entry = _load_album_cache(directory, album_name)
        old_set = set(cached_entry["assets"]) if cached_entry and "assets" in cached_entry else set()
        changed_asset_ids |= old_set ^ new_set

        if not dry_run:
            _save_album_cache(directory, album_name, {
                "smart": True,
                "assets": asset_ids,
            })

        logger.info("Smart album %s: %d assets", album_name, len(asset_ids))

    return album_sets, changed_asset_ids


def _incremental_fetch(
    library: PhotoLibrary,
    directory: str,
    sync_token: str,
    dry_run: bool,
) -> Tuple[Dict[str, Set[str]], Set[str], str | None]:
    """Incremental fetch via zone changes. Returns (album_sets, changed_ids, new_token).

    Returns new_token=None on error (caller should fall back to full fetch).
    """
    try:
        records, new_token = library.fetch_zone_changes(sync_token)
    except Exception:
        logger.warning("Zone change fetch failed, will fall back to full fetch", exc_info=True)
        return {}, set(), None

    # Load existing caches
    album_sets: Dict[str, Set[str]] = {}
    for album_name in SMART_ALBUM_FIELDS:
        cached_entry = _load_album_cache(directory, album_name)
        if cached_entry and "assets" in cached_entry:
            album_sets[album_name] = set(cached_entry["assets"])
        else:
            album_sets[album_name] = set()

    changed_asset_ids: Set[str] = set()

    for rec in records:
        record_type = rec.get("recordType", "")
        if record_type != "CPLAsset":
            continue

        asset_id = rec.get("recordName", "")
        if not asset_id:
            continue

        # Handle deleted records
        if rec.get("deleted", False):
            for album_name in SMART_ALBUM_FIELDS:
                if asset_id in album_sets[album_name]:
                    album_sets[album_name].discard(asset_id)
                    changed_asset_ids.add(asset_id)
            continue

        fields = rec.get("fields", {})
        for album_name, (field_name, active_value) in SMART_ALBUM_FIELDS.items():
            if field_name not in fields:
                continue

            is_member = fields[field_name].get("value") == active_value
            was_member = asset_id in album_sets[album_name]

            if is_member and not was_member:
                album_sets[album_name].add(asset_id)
                changed_asset_ids.add(asset_id)
            elif not is_member and was_member:
                album_sets[album_name].discard(asset_id)
                changed_asset_ids.add(asset_id)

    # Save updated caches
    if changed_asset_ids and not dry_run:
        for album_name in SMART_ALBUM_FIELDS:
            _save_album_cache(directory, album_name, {
                "smart": True,
                "assets": sorted(album_sets[album_name]),
            })

    if changed_asset_ids:
        logger.info("Zone changes affected %d asset(s) in smart albums", len(changed_asset_ids))
    else:
        logger.debug("No smart album changes detected via zone tracking")

    return album_sets, changed_asset_ids, new_token


def build_smart_album_membership(
    library: PhotoLibrary,
    directory: str,
    dry_run: bool,
) -> AlbumMembershipResult:
    """Build album membership for Favorites and Hidden smart albums.

    Uses zone change tracking for incremental updates when a sync token exists.
    Falls back to full fetch on first run or token expiry.
    """
    sync_state = _load_sync_state(directory)
    sync_token = sync_state.get("sync_token") if sync_state else None

    album_sets: Dict[str, Set[str]]
    changed_asset_ids: Set[str]

    if sync_token:
        album_sets, changed_asset_ids, new_token = _incremental_fetch(
            library, directory, sync_token, dry_run
        )
        if new_token is None:
            # Fallback: token expired or error
            logger.warning("Sync token expired, performing full smart album fetch")
            album_sets, changed_asset_ids = _initial_fetch(library, directory, dry_run)
            new_token = library.get_sync_token()
        else:
            pass
    else:
        logger.info("No sync token found, performing initial smart album fetch")
        album_sets, changed_asset_ids = _initial_fetch(library, directory, dry_run)
        new_token = library.get_sync_token()

    # Save sync state
    if new_token and not dry_run:
        _save_sync_state(directory, {"sync_token": new_token})

    # Build membership dict: asset_id -> [(album_name, None), ...]
    membership: Dict[str, List[Tuple[str, str | None]]] = {}
    for album_name in SMART_ALBUM_FIELDS:
        for asset_id in album_sets.get(album_name, set()):
            membership.setdefault(asset_id, []).append((album_name, None))

    return AlbumMembershipResult(membership=membership, changed_asset_ids=changed_asset_ids)
