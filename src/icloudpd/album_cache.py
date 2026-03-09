import json
import logging
import os
import tempfile
from typing import Any, Dict, List, NamedTuple, Set, Tuple

from pyicloud_ipd.services.photos import PhotoAlbum

logger = logging.getLogger(__name__)

CACHE_DIR = ".albums"


class AlbumMembershipResult(NamedTuple):
    membership: Dict[str, List[Tuple[str, str | None]]]
    changed_asset_ids: Set[str]


def _album_cache_path(directory: str, album_name: str) -> str:
    return os.path.join(directory, CACHE_DIR, f"{album_name}.json")


def _load_album_cache(directory: str, album_name: str) -> Dict[str, Any] | None:
    path = _album_cache_path(directory, album_name)
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and ("uuid" in data or data.get("smart")):
            return data
        return None
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _save_album_cache(directory: str, album_name: str, data: Dict[str, Any]) -> None:
    path = _album_cache_path(directory, album_name)
    cache_dir = os.path.dirname(path)
    try:
        os.makedirs(cache_dir, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception:
        logger.warning("Failed to save album cache to %s", path, exc_info=True)


def build_album_membership_cached(
    albums_dict: Dict[str, PhotoAlbum],
    directory: str,
    dry_run: bool,
) -> AlbumMembershipResult:
    album_membership: Dict[str, List[Tuple[str, str | None]]] = {}
    changed_asset_ids: Set[str] = set()
    fetched_count = 0

    for album_name, album in albums_dict.items():
        if album.uuid is None:
            continue

        cached_entry = _load_album_cache(directory, album_name)
        if (
            cached_entry
            and cached_entry.get("uuid") == album.uuid
            and cached_entry.get("record_change_tag") == album.record_change_tag
            and album.record_change_tag is not None
        ):
            asset_ids = cached_entry["assets"]
            logger.debug("Album cache hit: %s", album_name)
        else:
            logger.debug("Album cache miss: %s", album_name)
            old_assets = set(cached_entry["assets"]) if cached_entry and "assets" in cached_entry else set()
            asset_ids = [photo.asset_id for photo in album]
            new_assets = set(asset_ids)
            changed_asset_ids |= old_assets ^ new_assets
            fetched_count += 1
            if not dry_run:
                _save_album_cache(directory, album_name, {
                    "uuid": album.uuid,
                    "record_change_tag": album.record_change_tag,
                    "assets": asset_ids,
                })
                logger.debug("Album cache saved: %s (%d assets)", album_name, len(asset_ids))

        for asset_id in asset_ids:
            album_membership.setdefault(asset_id, []).append(
                (album.name, album.uuid)
            )

    if fetched_count:
        logger.info("Fetched membership for %d album(s)", fetched_count)
    else:
        logger.debug("All album memberships served from cache")

    return AlbumMembershipResult(membership=album_membership, changed_asset_ids=changed_asset_ids)
