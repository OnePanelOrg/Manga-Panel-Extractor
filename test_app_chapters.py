import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

import app
from chapter_contract import SegmentationMode, chapter_cache_key


class ChapterProcessingTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        data_directory = Path(self.temporary_directory.name)
        self.images_directory = data_directory / "images"
        self.results_directory = data_directory / "jsons"
        self.images_directory.mkdir()
        self.results_directory.mkdir()
        self.directories = patch.multiple(
            app,
            IMAGES_DIR=self.images_directory,
            JSONS_DIR=self.results_directory,
        )
        self.directories.start()

    def tearDown(self):
        self.directories.stop()
        self.temporary_directory.cleanup()

    @patch("app.Kumiko")
    @patch("app.download_lmages")
    def test_processing_writes_result_and_reuses_mode_cache(
        self,
        download_images,
        kumiko,
    ):
        source_url = "https://opchapters.com/chapter/1?tracking=yes"
        detector = MagicMock()
        detector.parse_dir.return_value = {
            "pageCount": 1,
            "pages": [{"filename": "1.png"}],
        }
        kumiko.return_value = detector
        download_images.return_value = 1

        first = app.process_chapter(source_url, SegmentationMode.STANDARD)
        second = app.process_chapter(
            "https://opchapters.com/chapter/1?tracking=other",
            SegmentationMode.STANDARD,
        )

        self.assertEqual(first, second)
        self.assertEqual(download_images.call_count, 1)
        result_directory = self.results_directory / first["chapter_hash"]
        self.assertTrue((result_directory / "kumiko.json").exists())
        self.assertEqual(
            json.loads((result_directory / "metadata.json").read_text()),
            {
                "segmentation_mode": "standard",
                "access_policy": "public",
            },
        )

    @patch("app.Kumiko")
    @patch("app.download_lmages")
    def test_premium_processing_uses_a_separate_cache(
        self,
        download_images,
        kumiko,
    ):
        source_url = "https://opchapters.com/chapter/1"
        detector = MagicMock()
        detector.parse_dir.return_value = {
            "pageCount": 1,
            "pages": [{"filename": "1.png"}],
        }
        kumiko.return_value = detector
        download_images.return_value = 1

        standard = app.process_chapter(source_url, SegmentationMode.STANDARD)
        premium = app.process_chapter(
            source_url,
            SegmentationMode.GPT_5_6_LAYOUT,
        )

        self.assertNotEqual(standard["chapter_hash"], premium["chapter_hash"])
        self.assertEqual(download_images.call_count, 2)

    def test_missing_result_is_not_found(self):
        chapter_hash = chapter_cache_key(
            "https://opchapters.com/missing",
            SegmentationMode.STANDARD,
        )
        with patch("app.require_active_subscription"):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(app.get_chapter(chapter_hash, "user_123"))

        self.assertEqual(raised.exception.status_code, 404)

    def test_chapter_url_validation_accepts_supported_https_host(self):
        source_url = "https://www.opchapters.com/chapter/1?date=latest"

        self.assertEqual(app.validate_chapter_url(source_url), source_url)

    def test_chapter_url_validation_rejects_other_origins(self):
        for source_url in (
            "http://opchapters.com/chapter/1",
            "https://opchapters.com.attacker.example/chapter/1",
            "https://example.com/chapter/1",
        ):
            with self.subTest(source_url=source_url):
                with self.assertRaises(HTTPException) as raised:
                    app.validate_chapter_url(source_url)
                self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
