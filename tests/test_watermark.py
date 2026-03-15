"""Tests for until-found watermark persistence."""

import json
import os
import tempfile
import unittest

from icloudpd.watermark import get_watermark, load_watermarks, save_watermark


class WatermarkTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_load_empty(self):
        """No watermark file returns empty dict."""
        self.assertEqual(load_watermarks(self.tmp_dir), {})

    def test_get_no_watermark(self):
        """get_watermark returns None when no data exists."""
        self.assertIsNone(get_watermark(self.tmp_dir, "All Photos"))

    def test_save_and_load(self):
        save_watermark(self.tmp_dir, "All Photos", 1710000000000, "ABC123", completed=False, dry_run=False)
        wm = get_watermark(self.tmp_dir, "All Photos")
        self.assertIsNotNone(wm)
        self.assertEqual(wm["asset_date_ms"], 1710000000000)
        self.assertEqual(wm["asset_id"], "ABC123")
        self.assertFalse(wm["completed"])

    def test_save_completed(self):
        save_watermark(self.tmp_dir, "", 1710000000000, "ABC123", completed=False, dry_run=False)
        save_watermark(self.tmp_dir, "", 1709000000000, "DEF456", completed=True, dry_run=False)
        wm = get_watermark(self.tmp_dir, "")
        self.assertTrue(wm["completed"])
        self.assertEqual(wm["asset_date_ms"], 1709000000000)

    def test_multiple_albums(self):
        save_watermark(self.tmp_dir, "", 1710000000000, "A1", completed=False, dry_run=False)
        save_watermark(self.tmp_dir, "Vacation", 1709000000000, "B2", completed=True, dry_run=False)
        self.assertEqual(get_watermark(self.tmp_dir, "")["asset_id"], "A1")
        self.assertEqual(get_watermark(self.tmp_dir, "Vacation")["asset_id"], "B2")
        self.assertIsNone(get_watermark(self.tmp_dir, "Other"))

    def test_dry_run_does_not_save(self):
        save_watermark(self.tmp_dir, "", 1710000000000, "ABC123", completed=False, dry_run=True)
        self.assertIsNone(get_watermark(self.tmp_dir, ""))

    def test_corrupted_file_returns_empty(self):
        cache_dir = os.path.join(self.tmp_dir, ".albums")
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, ".until_found_watermark.json"), "w") as f:
            f.write("not json")
        self.assertEqual(load_watermarks(self.tmp_dir), {})


if __name__ == "__main__":
    unittest.main()
