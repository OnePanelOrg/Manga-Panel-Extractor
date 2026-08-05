import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from PIL import Image

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

    @patch("app.Kumiko")
    def test_uploaded_chapter_reuses_json_and_deletes_all_page_files(self, kumiko):
        image = io.BytesIO()
        Image.new("RGB", (24, 32), "white").save(image, format="PNG")

        detector = MagicMock()
        detector.parse_dir.return_value = {
            "pageCount": 1,
            "pages": [{
                "filename": "0001.webp",
                "image": "upload://digest/0001.webp",
                "panels": [{"path": "0 0"}],
            }],
        }
        kumiko.return_value = detector

        def upload():
            return MagicMock(filename="page.png", file=io.BytesIO(image.getvalue()))

        temporary_roots = []
        real_ingest_uploads = app.ingest_uploads

        def capture_ingestion(*args, **kwargs):
            chapter = real_ingest_uploads(*args, **kwargs)
            temporary_roots.append(chapter.directory.parent)
            return chapter

        with patch("app.ingest_uploads", side_effect=capture_ingestion):
            first = app.process_uploaded_chapter(
                [upload()],
                SegmentationMode.STANDARD,
            )
            second = app.process_uploaded_chapter(
                [upload()],
                SegmentationMode.STANDARD,
            )

        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(first["chapter_hash"], second["chapter_hash"])
        self.assertEqual(detector.parse_dir.call_count, 1)
        self.assertTrue(
            first["chapter"]["pages"][0]["image"].startswith(
                "data:image/webp;base64,"
            )
        )
        self.assertTrue(
            second["chapter"]["pages"][0]["image"].startswith(
                "data:image/webp;base64,"
            )
        )
        result = json.loads(
            (
                self.results_directory
                / first["chapter_hash"]
                / "kumiko.json"
            ).read_text()
        )
        self.assertEqual(result["pageCount"], 1)
        self.assertTrue(result["pages"][0]["image"].startswith("upload://"))
        self.assertNotIn("data:image", json.dumps(result))
        self.assertTrue(temporary_roots)
        self.assertTrue(all(not root.exists() for root in temporary_roots))

    @patch("app.Kumiko")
    def test_page_count_mismatch_is_not_cached(self, kumiko):
        image = io.BytesIO()
        Image.new("RGB", (24, 32), "white").save(image, format="PNG")
        detector = MagicMock()
        detector.parse_dir.return_value = {
            "pageCount": 1,
            "pages": [{
                "filename": "0001.webp",
                "image": "upload://digest/0001.webp",
                "panels": [{"path": "0 0"}],
            }],
        }
        kumiko.return_value = detector
        uploads = [
            MagicMock(filename=f"{index}.png", file=io.BytesIO(image.getvalue()))
            for index in (1, 2)
        ]

        with self.assertRaises(HTTPException) as raised:
            app.process_uploaded_chapter(uploads, SegmentationMode.STANDARD)

        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(list(self.results_directory.rglob("kumiko.json")), [])

    def test_cached_upload_requires_reupload_for_later_retrieval(self):
        chapter_hash = "uploaded"
        result_directory = self.results_directory / chapter_hash
        result_directory.mkdir()
        (result_directory / "kumiko.json").write_text(json.dumps({
            "pages": [{"image": "upload://digest/0001.webp"}],
        }))

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(app.get_chapter(chapter_hash, None))

        self.assertEqual(raised.exception.status_code, 409)

    def test_concurrent_upload_is_rejected_without_running_extractor(self):
        extractor = MagicMock()
        app.extraction_lock.acquire()
        try:
            with self.assertRaises(HTTPException) as raised:
                app.run_upload_extraction(extractor, [])
        finally:
            app.extraction_lock.release()

        self.assertEqual(raised.exception.status_code, 429)
        extractor.assert_not_called()

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
        for source_url in (
            "https://www.opchapters.com/chapter/1?date=latest",
            (
                "https://tcbonepiecechapters.com/chapters/7996/"
                "one-piece-chapter-1189"
            ),
            "https://www.tcbonepiecechapters.com/chapters/7995/chapter",
        ):
            with self.subTest(source_url=source_url):
                self.assertEqual(app.validate_chapter_url(source_url), source_url)

    def test_chapter_url_validation_rejects_other_origins(self):
        for source_url in (
            "http://opchapters.com/chapter/1",
            "http://tcbonepiecechapters.com/chapters/7996/chapter",
            "https://opchapters.com.attacker.example/chapter/1",
            "https://tcbonepiecechapters.com.attacker.example/chapters/1",
            "https://example.com/chapter/1",
        ):
            with self.subTest(source_url=source_url):
                with self.assertRaises(HTTPException) as raised:
                    app.validate_chapter_url(source_url)
                self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
