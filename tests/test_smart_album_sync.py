import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from icloudpd.album_cache import CACHE_DIR, AlbumMembershipResult, _album_cache_path
from icloudpd.smart_album_sync import (
    SYNC_STATE_FILE,
    _incremental_fetch,
    _initial_fetch,
    _load_sync_state,
    _save_sync_state,
    build_smart_album_membership,
)


def _write_cache(directory, album_name, data):
    path = _album_cache_path(directory, album_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _read_cache(directory, album_name):
    path = _album_cache_path(directory, album_name)
    with open(path) as f:
        return json.load(f)


def _make_library_with_albums(favorites_ids=None, hidden_ids=None):
    """Create a mock PhotoLibrary with Favorites and Hidden smart albums."""
    library = MagicMock()

    fav_album = MagicMock()
    fav_album.fetch_asset_ids.return_value = favorites_ids or []
    fav_album.name = "Favorites"

    hidden_album = MagicMock()
    hidden_album.fetch_asset_ids.return_value = hidden_ids or []
    hidden_album.name = "Hidden"

    library.albums = {"Favorites": fav_album, "Hidden": hidden_album}
    return library


class TestSyncStatePersistence(unittest.TestCase):
    def test_load_missing(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(_load_sync_state(d))

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            _save_sync_state(d, {"sync_token": "tok123"})
            state = _load_sync_state(d)
            self.assertEqual(state, {"sync_token": "tok123"})

    def test_load_corrupt(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, CACHE_DIR, SYNC_STATE_FILE)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("not json")
            self.assertIsNone(_load_sync_state(d))


class TestInitialFetch(unittest.TestCase):
    def test_fetches_both_albums(self):
        with tempfile.TemporaryDirectory() as d:
            library = _make_library_with_albums(
                favorites_ids=["A1", "A2"], hidden_ids=["A3"]
            )
            album_sets, changed = _initial_fetch(library, d, dry_run=False)

            self.assertEqual(album_sets["Favorites"], {"A1", "A2"})
            self.assertEqual(album_sets["Hidden"], {"A3"})
            # All are changed on first run (no prior cache)
            self.assertEqual(changed, {"A1", "A2", "A3"})

            # Caches written
            fav_cache = _read_cache(d, "Favorites")
            self.assertTrue(fav_cache["smart"])
            self.assertEqual(sorted(fav_cache["assets"]), ["A1", "A2"])

    def test_detects_changes_from_prior_cache(self):
        with tempfile.TemporaryDirectory() as d:
            _write_cache(d, "Favorites", {"smart": True, "assets": ["A1", "OLD"]})
            _write_cache(d, "Hidden", {"smart": True, "assets": []})

            library = _make_library_with_albums(
                favorites_ids=["A1", "A2"], hidden_ids=[]
            )
            album_sets, changed = _initial_fetch(library, d, dry_run=False)

            self.assertEqual(album_sets["Favorites"], {"A1", "A2"})
            # OLD removed, A2 added → both changed
            self.assertIn("OLD", changed)
            self.assertIn("A2", changed)

    def test_dry_run_no_write(self):
        with tempfile.TemporaryDirectory() as d:
            library = _make_library_with_albums(favorites_ids=["A1"])
            _initial_fetch(library, d, dry_run=True)
            self.assertFalse(os.path.exists(_album_cache_path(d, "Favorites")))

    def test_missing_album_in_library(self):
        with tempfile.TemporaryDirectory() as d:
            library = MagicMock()
            library.albums = {}  # No smart albums at all
            album_sets, changed = _initial_fetch(library, d, dry_run=False)
            self.assertEqual(album_sets["Favorites"], set())
            self.assertEqual(album_sets["Hidden"], set())


class TestIncrementalFetch(unittest.TestCase):
    def test_favorite_added(self):
        with tempfile.TemporaryDirectory() as d:
            _write_cache(d, "Favorites", {"smart": True, "assets": []})
            _write_cache(d, "Hidden", {"smart": True, "assets": []})

            library = MagicMock()
            library.fetch_zone_changes.return_value = (
                [
                    {
                        "recordType": "CPLAsset",
                        "recordName": "A1",
                        "fields": {
                            "isFavorite": {"value": 1},
                            "isHidden": {"value": 0},
                        },
                    }
                ],
                "new-token",
            )

            album_sets, changed, token = _incremental_fetch(
                library, d, "old-token", dry_run=False
            )

            self.assertIn("A1", album_sets["Favorites"])
            self.assertNotIn("A1", album_sets["Hidden"])
            self.assertEqual(changed, {"A1"})
            self.assertEqual(token, "new-token")

            # Cache updated
            fav_cache = _read_cache(d, "Favorites")
            self.assertIn("A1", fav_cache["assets"])

    def test_favorite_removed(self):
        with tempfile.TemporaryDirectory() as d:
            _write_cache(d, "Favorites", {"smart": True, "assets": ["A1"]})
            _write_cache(d, "Hidden", {"smart": True, "assets": []})

            library = MagicMock()
            library.fetch_zone_changes.return_value = (
                [
                    {
                        "recordType": "CPLAsset",
                        "recordName": "A1",
                        "fields": {
                            "isFavorite": {"value": 0},
                        },
                    }
                ],
                "new-token",
            )

            album_sets, changed, token = _incremental_fetch(
                library, d, "old-token", dry_run=False
            )

            self.assertNotIn("A1", album_sets["Favorites"])
            self.assertEqual(changed, {"A1"})

    def test_hidden_toggled(self):
        with tempfile.TemporaryDirectory() as d:
            _write_cache(d, "Favorites", {"smart": True, "assets": []})
            _write_cache(d, "Hidden", {"smart": True, "assets": []})

            library = MagicMock()
            library.fetch_zone_changes.return_value = (
                [
                    {
                        "recordType": "CPLAsset",
                        "recordName": "B1",
                        "fields": {
                            "isHidden": {"value": 1},
                        },
                    }
                ],
                "tok2",
            )

            album_sets, changed, token = _incremental_fetch(
                library, d, "tok1", dry_run=False
            )

            self.assertIn("B1", album_sets["Hidden"])
            self.assertIn("B1", changed)

    def test_deleted_record(self):
        with tempfile.TemporaryDirectory() as d:
            _write_cache(d, "Favorites", {"smart": True, "assets": ["A1"]})
            _write_cache(d, "Hidden", {"smart": True, "assets": ["A1"]})

            library = MagicMock()
            library.fetch_zone_changes.return_value = (
                [
                    {
                        "recordType": "CPLAsset",
                        "recordName": "A1",
                        "deleted": True,
                    }
                ],
                "tok2",
            )

            album_sets, changed, token = _incremental_fetch(
                library, d, "tok1", dry_run=False
            )

            self.assertNotIn("A1", album_sets["Favorites"])
            self.assertNotIn("A1", album_sets["Hidden"])
            self.assertEqual(changed, {"A1"})

    def test_no_changes(self):
        with tempfile.TemporaryDirectory() as d:
            _write_cache(d, "Favorites", {"smart": True, "assets": ["A1"]})
            _write_cache(d, "Hidden", {"smart": True, "assets": []})

            library = MagicMock()
            library.fetch_zone_changes.return_value = ([], "tok2")

            album_sets, changed, token = _incremental_fetch(
                library, d, "tok1", dry_run=False
            )

            self.assertEqual(album_sets["Favorites"], {"A1"})
            self.assertEqual(changed, set())
            self.assertEqual(token, "tok2")

    def test_api_error_returns_none_token(self):
        with tempfile.TemporaryDirectory() as d:
            _write_cache(d, "Favorites", {"smart": True, "assets": []})
            _write_cache(d, "Hidden", {"smart": True, "assets": []})

            library = MagicMock()
            library.fetch_zone_changes.side_effect = Exception("API error")

            album_sets, changed, token = _incremental_fetch(
                library, d, "tok1", dry_run=False
            )

            self.assertIsNone(token)

    def test_non_cplasset_records_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            _write_cache(d, "Favorites", {"smart": True, "assets": []})
            _write_cache(d, "Hidden", {"smart": True, "assets": []})

            library = MagicMock()
            library.fetch_zone_changes.return_value = (
                [
                    {
                        "recordType": "CPLMaster",
                        "recordName": "M1",
                        "fields": {"isFavorite": {"value": 1}},
                    }
                ],
                "tok2",
            )

            _, changed, _ = _incremental_fetch(library, d, "tok1", dry_run=False)
            self.assertEqual(changed, set())

    def test_dry_run_no_cache_update(self):
        with tempfile.TemporaryDirectory() as d:
            _write_cache(d, "Favorites", {"smart": True, "assets": []})
            _write_cache(d, "Hidden", {"smart": True, "assets": []})

            library = MagicMock()
            library.fetch_zone_changes.return_value = (
                [
                    {
                        "recordType": "CPLAsset",
                        "recordName": "A1",
                        "fields": {"isFavorite": {"value": 1}},
                    }
                ],
                "tok2",
            )

            album_sets, changed, _ = _incremental_fetch(
                library, d, "tok1", dry_run=True
            )
            self.assertIn("A1", album_sets["Favorites"])
            self.assertEqual(changed, {"A1"})

            # Cache NOT updated on disk
            cache = _read_cache(d, "Favorites")
            self.assertEqual(cache["assets"], [])


class TestBuildSmartAlbumMembership(unittest.TestCase):
    def test_initial_sync_no_token(self):
        with tempfile.TemporaryDirectory() as d:
            library = _make_library_with_albums(
                favorites_ids=["A1", "A2"], hidden_ids=["A3"]
            )
            library.get_sync_token.return_value = "initial-token"

            result = build_smart_album_membership(library, d, dry_run=False)

            self.assertIsInstance(result, AlbumMembershipResult)
            self.assertIn("A1", result.membership)
            self.assertEqual(result.membership["A1"], [("Favorites", None)])
            self.assertIn("A3", result.membership)
            self.assertEqual(result.membership["A3"], [("Hidden", None)])
            self.assertEqual(result.changed_asset_ids, {"A1", "A2", "A3"})

            # Sync state saved
            state = _load_sync_state(d)
            self.assertEqual(state["sync_token"], "initial-token")

    def test_incremental_sync_with_token(self):
        with tempfile.TemporaryDirectory() as d:
            # Pre-populate sync state and caches
            _save_sync_state(d, {"sync_token": "old-token"})
            _write_cache(d, "Favorites", {"smart": True, "assets": ["A1"]})
            _write_cache(d, "Hidden", {"smart": True, "assets": []})

            library = MagicMock()
            library.fetch_zone_changes.return_value = (
                [
                    {
                        "recordType": "CPLAsset",
                        "recordName": "A2",
                        "fields": {"isFavorite": {"value": 1}},
                    }
                ],
                "new-token",
            )

            result = build_smart_album_membership(library, d, dry_run=False)

            self.assertIn("A1", result.membership)
            self.assertIn("A2", result.membership)
            self.assertEqual(result.changed_asset_ids, {"A2"})

            state = _load_sync_state(d)
            self.assertEqual(state["sync_token"], "new-token")

    def test_fallback_on_token_expiry(self):
        with tempfile.TemporaryDirectory() as d:
            _save_sync_state(d, {"sync_token": "expired-token"})
            _write_cache(d, "Favorites", {"smart": True, "assets": ["OLD"]})
            _write_cache(d, "Hidden", {"smart": True, "assets": []})

            library = MagicMock()
            library.fetch_zone_changes.side_effect = Exception("Token expired")
            library.get_sync_token.return_value = "fresh-token"

            # Set up albums for fallback full fetch
            fav_album = MagicMock()
            fav_album.fetch_asset_ids.return_value = ["A1"]
            fav_album.name = "Favorites"
            hidden_album = MagicMock()
            hidden_album.fetch_asset_ids.return_value = []
            hidden_album.name = "Hidden"
            library.albums = {"Favorites": fav_album, "Hidden": hidden_album}

            result = build_smart_album_membership(library, d, dry_run=False)

            self.assertIn("A1", result.membership)
            self.assertNotIn("OLD", result.membership)
            # OLD removed, A1 added
            self.assertIn("OLD", result.changed_asset_ids)
            self.assertIn("A1", result.changed_asset_ids)

            state = _load_sync_state(d)
            self.assertEqual(state["sync_token"], "fresh-token")

    def test_dry_run_no_sync_state_saved(self):
        with tempfile.TemporaryDirectory() as d:
            library = _make_library_with_albums(favorites_ids=["A1"])
            library.get_sync_token.return_value = "tok"

            result = build_smart_album_membership(library, d, dry_run=True)

            self.assertIn("A1", result.membership)
            self.assertIsNone(_load_sync_state(d))

    def test_both_favorite_and_hidden(self):
        """An asset can be both Favorite and Hidden."""
        with tempfile.TemporaryDirectory() as d:
            library = _make_library_with_albums(
                favorites_ids=["A1"], hidden_ids=["A1"]
            )
            library.get_sync_token.return_value = "tok"

            result = build_smart_album_membership(library, d, dry_run=False)

            self.assertIn("A1", result.membership)
            album_names = [name for name, _ in result.membership["A1"]]
            self.assertIn("Favorites", album_names)
            self.assertIn("Hidden", album_names)


class TestMergedMembership(unittest.TestCase):
    """Test that smart album membership format integrates correctly with regular albums."""

    def test_membership_tuple_format(self):
        """Smart album entries use (name, None) tuples."""
        with tempfile.TemporaryDirectory() as d:
            library = _make_library_with_albums(favorites_ids=["A1"])
            library.get_sync_token.return_value = "tok"

            result = build_smart_album_membership(library, d, dry_run=False)

            self.assertEqual(result.membership["A1"], [("Favorites", None)])

    def test_empty_albums(self):
        with tempfile.TemporaryDirectory() as d:
            library = _make_library_with_albums(favorites_ids=[], hidden_ids=[])
            library.get_sync_token.return_value = "tok"

            result = build_smart_album_membership(library, d, dry_run=False)

            self.assertEqual(result.membership, {})
            self.assertEqual(result.changed_asset_ids, set())
