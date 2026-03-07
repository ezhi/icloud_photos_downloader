import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock

from icloudpd.album_cache import build_album_membership_cached, _load_album_cache, _save_album_cache, CACHE_DIR, AlbumMembershipResult


def _make_album(name, uuid=None, record_change_tag=None, photos=None):
    album = MagicMock()
    album.name = name
    album.uuid = uuid
    album.record_change_tag = record_change_tag
    if photos is not None:
        photo_mocks = []
        for pid in photos:
            p = MagicMock()
            p.asset_id = pid
            photo_mocks.append(p)
        album.__iter__ = MagicMock(return_value=iter(photo_mocks))
    else:
        album.__iter__ = MagicMock(return_value=iter([]))
    return album


def _write_album_cache(directory, album_name, data):
    path = os.path.join(directory, CACHE_DIR, f"{album_name}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)


def _read_album_cache(directory, album_name):
    path = os.path.join(directory, CACHE_DIR, f"{album_name}.json")
    with open(path) as f:
        return json.load(f)


class TestAlbumCacheIO(unittest.TestCase):
    def test_load_no_file(self):
        with tempfile.TemporaryDirectory() as d:
            result = _load_album_cache(d, "NoSuchAlbum")
            self.assertIsNone(result)

    def test_load_valid(self):
        with tempfile.TemporaryDirectory() as d:
            data = {"uuid": "abc", "record_change_tag": "t1", "assets": ["p1"]}
            _write_album_cache(d, "Vacation", data)
            result = _load_album_cache(d, "Vacation")
            self.assertEqual(result, data)

    def test_load_malformed(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, CACHE_DIR, "Bad.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("not json {{{")
            result = _load_album_cache(d, "Bad")
            self.assertIsNone(result)

    def test_save_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            data = {"uuid": "x", "record_change_tag": "t", "assets": []}
            _save_album_cache(d, "Test", data)

            cache_dir = os.path.join(d, CACHE_DIR)
            self.assertTrue(os.path.exists(os.path.join(cache_dir, "Test.json")))

            # No .tmp files left behind
            tmp_files = [f for f in os.listdir(cache_dir) if f.endswith(".tmp")]
            self.assertEqual(tmp_files, [])

            result = _load_album_cache(d, "Test")
            self.assertEqual(result, data)

    def test_save_nested_path(self):
        with tempfile.TemporaryDirectory() as d:
            data = {"uuid": "x", "record_change_tag": "t", "assets": ["p1"]}
            _save_album_cache(d, "2025/November/Trip", data)

            result = _load_album_cache(d, "2025/November/Trip")
            self.assertEqual(result, data)

            # Verify directory structure
            expected = os.path.join(d, CACHE_DIR, "2025", "November", "Trip.json")
            self.assertTrue(os.path.exists(expected))


class TestBuildAlbumMembershipCached(unittest.TestCase):
    def test_build_membership_no_cache(self):
        with tempfile.TemporaryDirectory() as d:
            album = _make_album("Vacation", uuid="abc", record_change_tag="tag1", photos=["p1", "p2"])
            albums_dict = {"Vacation": album}
            result = build_album_membership_cached(albums_dict, d, dry_run=False)

            self.assertIsInstance(result, AlbumMembershipResult)
            self.assertIn("p1", result.membership)
            self.assertIn("p2", result.membership)
            self.assertEqual(result.membership["p1"], [("Vacation", "abc")])
            # No prior cache, so all assets are "changed"
            self.assertEqual(result.changed_asset_ids, {"p1", "p2"})

            cache = _read_album_cache(d, "Vacation")
            self.assertEqual(cache["assets"], ["p1", "p2"])
            self.assertEqual(cache["record_change_tag"], "tag1")

    def test_build_membership_cache_hit(self):
        with tempfile.TemporaryDirectory() as d:
            _write_album_cache(d, "Vacation", {
                "uuid": "abc",
                "record_change_tag": "tag1",
                "assets": ["p1", "p2"],
            })

            album = _make_album("Vacation", uuid="abc", record_change_tag="tag1")
            albums_dict = {"Vacation": album}
            result = build_album_membership_cached(albums_dict, d, dry_run=False)

            album.__iter__.assert_not_called()
            self.assertEqual(result.membership["p1"], [("Vacation", "abc")])
            self.assertEqual(result.membership["p2"], [("Vacation", "abc")])
            self.assertEqual(result.changed_asset_ids, set())

    def test_build_membership_cache_miss(self):
        with tempfile.TemporaryDirectory() as d:
            _write_album_cache(d, "Vacation", {
                "uuid": "abc",
                "record_change_tag": "old_tag",
                "assets": ["p1"],
            })

            album = _make_album("Vacation", uuid="abc", record_change_tag="new_tag", photos=["p1", "p2", "p3"])
            albums_dict = {"Vacation": album}
            result = build_album_membership_cached(albums_dict, d, dry_run=False)

            album.__iter__.assert_called_once()
            self.assertEqual(len(result.membership), 3)
            # p2 and p3 are new (symmetric difference of {p1} and {p1,p2,p3})
            self.assertEqual(result.changed_asset_ids, {"p2", "p3"})

            cache = _read_album_cache(d, "Vacation")
            self.assertEqual(cache["record_change_tag"], "new_tag")
            self.assertEqual(cache["assets"], ["p1", "p2", "p3"])

    def test_build_membership_nested_album(self):
        with tempfile.TemporaryDirectory() as d:
            album = _make_album("2025/Nov/Trip", uuid="abc", record_change_tag="t1", photos=["p1"])
            albums_dict = {"2025/Nov/Trip": album}
            result = build_album_membership_cached(albums_dict, d, dry_run=False)

            self.assertIn("p1", result.membership)
            cache = _read_album_cache(d, "2025/Nov/Trip")
            self.assertEqual(cache["assets"], ["p1"])

    def test_build_membership_dry_run(self):
        with tempfile.TemporaryDirectory() as d:
            album = _make_album("Vacation", uuid="abc", record_change_tag="tag1", photos=["p1"])
            albums_dict = {"Vacation": album}
            result = build_album_membership_cached(albums_dict, d, dry_run=True)

            self.assertIn("p1", result.membership)
            self.assertFalse(os.path.exists(os.path.join(d, CACHE_DIR)))

    def test_build_membership_smart_albums_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            smart = _make_album("Favorites", uuid=None, photos=["p1"])
            user_album = _make_album("My Album", uuid="u1", record_change_tag="t1", photos=["p2"])
            albums_dict = {"Favorites": smart, "My Album": user_album}
            result = build_album_membership_cached(albums_dict, d, dry_run=False)

            smart.__iter__.assert_not_called()
            self.assertNotIn("p1", result.membership)
            self.assertIn("p2", result.membership)

            self.assertIsNone(_load_album_cache(d, "Favorites"))

    def test_build_membership_none_record_change_tag_forces_refetch(self):
        with tempfile.TemporaryDirectory() as d:
            _write_album_cache(d, "Album", {
                "uuid": "abc",
                "record_change_tag": None,
                "assets": ["old_p"],
            })

            album = _make_album("Album", uuid="abc", record_change_tag=None, photos=["new_p"])
            albums_dict = {"Album": album}
            result = build_album_membership_cached(albums_dict, d, dry_run=False)

            album.__iter__.assert_called_once()
            self.assertIn("new_p", result.membership)
            # old_p removed, new_p added
            self.assertEqual(result.changed_asset_ids, {"old_p", "new_p"})

    def test_build_membership_removed_asset_detected(self):
        with tempfile.TemporaryDirectory() as d:
            _write_album_cache(d, "Vacation", {
                "uuid": "abc",
                "record_change_tag": "old_tag",
                "assets": ["p1", "p2", "p3"],
            })

            album = _make_album("Vacation", uuid="abc", record_change_tag="new_tag", photos=["p1", "p3"])
            albums_dict = {"Vacation": album}
            result = build_album_membership_cached(albums_dict, d, dry_run=False)

            # p2 was removed
            self.assertEqual(result.changed_asset_ids, {"p2"})


if __name__ == "__main__":
    unittest.main()
