import json
import os
import tempfile
import unittest

from icloudpd.asset_index import (
    INDEX_DIR,
    add_asset_path,
    index_entry_path,
    load_asset_entry,
    remove_asset_entry,
    save_asset_entry,
)


class TestIndexEntryPath(unittest.TestCase):
    def test_basic_path(self):
        path = index_entry_path("/photos", "0E454CB9-42BC-413B-8BB2-4A20F4BE1")
        self.assertEqual(
            path,
            os.path.join("/photos", INDEX_DIR, "0E", "0E454CB9-42BC-413B-8BB2-4A20F4BE1.json"),
        )

    def test_lowercase_sharded(self):
        path = index_entry_path("/photos", "abCD1234")
        self.assertEqual(
            path,
            os.path.join("/photos", INDEX_DIR, "AB", "abCD1234.json"),
        )


class TestLoadSaveAssetEntry(unittest.TestCase):
    def test_load_no_file(self):
        with tempfile.TemporaryDirectory() as d:
            result = load_asset_entry(d, "NO-SUCH-ASSET")
            self.assertIsNone(result)

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            save_asset_entry(d, "ABC-123", ["2022/03/IMG_1.JPG"], dry_run=False)
            result = load_asset_entry(d, "ABC-123")
            self.assertEqual(result, ["2022/03/IMG_1.JPG"])

    def test_save_dry_run(self):
        with tempfile.TemporaryDirectory() as d:
            save_asset_entry(d, "ABC-123", ["path.jpg"], dry_run=True)
            result = load_asset_entry(d, "ABC-123")
            self.assertIsNone(result)

    def test_save_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            save_asset_entry(d, "ABC-123", ["old.jpg"], dry_run=False)
            save_asset_entry(d, "ABC-123", ["new.jpg"], dry_run=False)
            result = load_asset_entry(d, "ABC-123")
            self.assertEqual(result, ["new.jpg"])

    def test_load_malformed(self):
        with tempfile.TemporaryDirectory() as d:
            path = index_entry_path(d, "BAD")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("not json {{{")
            result = load_asset_entry(d, "BAD")
            self.assertIsNone(result)

    def test_no_tmp_files_left(self):
        with tempfile.TemporaryDirectory() as d:
            save_asset_entry(d, "ABC-123", ["path.jpg"], dry_run=False)
            shard_dir = os.path.dirname(index_entry_path(d, "ABC-123"))
            tmp_files = [f for f in os.listdir(shard_dir) if f.endswith(".tmp")]
            self.assertEqual(tmp_files, [])


class TestAddAssetPath(unittest.TestCase):
    def test_add_new(self):
        with tempfile.TemporaryDirectory() as d:
            add_asset_path(d, "ABC-123", "2022/IMG_1.JPG", dry_run=False)
            result = load_asset_entry(d, "ABC-123")
            self.assertEqual(result, ["2022/IMG_1.JPG"])

    def test_add_appends(self):
        with tempfile.TemporaryDirectory() as d:
            add_asset_path(d, "ABC-123", "2022/IMG_1.JPG", dry_run=False)
            add_asset_path(d, "ABC-123", "2022/IMG_1.MOV", dry_run=False)
            result = load_asset_entry(d, "ABC-123")
            self.assertEqual(result, ["2022/IMG_1.JPG", "2022/IMG_1.MOV"])

    def test_add_no_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            add_asset_path(d, "ABC-123", "2022/IMG_1.JPG", dry_run=False)
            add_asset_path(d, "ABC-123", "2022/IMG_1.JPG", dry_run=False)
            result = load_asset_entry(d, "ABC-123")
            self.assertEqual(result, ["2022/IMG_1.JPG"])

    def test_add_dry_run(self):
        with tempfile.TemporaryDirectory() as d:
            add_asset_path(d, "ABC-123", "2022/IMG_1.JPG", dry_run=True)
            result = load_asset_entry(d, "ABC-123")
            self.assertIsNone(result)


class TestRemoveAssetEntry(unittest.TestCase):
    def test_remove_existing(self):
        with tempfile.TemporaryDirectory() as d:
            save_asset_entry(d, "ABC-123", ["path.jpg"], dry_run=False)
            remove_asset_entry(d, "ABC-123")
            result = load_asset_entry(d, "ABC-123")
            self.assertIsNone(result)

    def test_remove_nonexistent(self):
        with tempfile.TemporaryDirectory() as d:
            # Should not raise
            remove_asset_entry(d, "NO-SUCH")


if __name__ == "__main__":
    unittest.main()
