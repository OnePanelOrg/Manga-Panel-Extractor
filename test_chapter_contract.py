import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app import Data
from chapter_contract import (
    SegmentationMode,
    chapter_cache_key,
    detector_options_for,
    read_metadata,
    upload_cache_key,
    write_metadata,
)


class ChapterContractTest(unittest.TestCase):
    def test_standard_is_the_backward_compatible_default(self):
        request = Data(chapter_url="https://opchapters.com/chapter/1")

        self.assertEqual(request.segmentation_mode, SegmentationMode.STANDARD)

    def test_api_accepts_only_closed_product_mode_values(self):
        premium = Data(
            chapter_url="https://opchapters.com/chapter/1",
            segmentation_mode="gpt-5.6-layout",
        )
        self.assertEqual(
            premium.segmentation_mode,
            SegmentationMode.GPT_5_6_LAYOUT,
        )

        with self.assertRaises(ValidationError):
            Data(
                chapter_url="https://opchapters.com/chapter/1",
                segmentation_mode="openai/gpt-5.6",
            )
        with self.assertRaises(ValidationError):
            Data(
                chapter_url="https://opchapters.com/chapter/1",
                segmentation_mode="future-mode",
            )
        with self.assertRaises(ValidationError):
            Data(
                chapter_url="https://opchapters.com/chapter/1",
                provider_model="openai/gpt-5.6",
            )

    def test_standard_cache_identity_matches_legacy_url_normalization(self):
        source_url = "https://opchapters.com/chapter/1?date=2026-01-01"
        legacy_hash = hashlib.md5(
            b"https://opchapters.com/chapter/1",
        ).hexdigest()

        self.assertEqual(
            chapter_cache_key(source_url, SegmentationMode.STANDARD),
            legacy_hash,
        )
        self.assertEqual(
            chapter_cache_key(
                "https://opchapters.com/chapter/1?different=true",
                SegmentationMode.STANDARD,
            ),
            legacy_hash,
        )

    def test_modes_have_distinct_cache_identities(self):
        source_url = "https://opchapters.com/chapter/1"

        self.assertNotEqual(
            chapter_cache_key(source_url, SegmentationMode.STANDARD),
            chapter_cache_key(source_url, SegmentationMode.GPT_5_6_LAYOUT),
        )

    def test_uploaded_content_identity_is_provider_independent_and_mode_aware(self):
        digest = "a" * 64

        standard = upload_cache_key(digest, SegmentationMode.STANDARD)
        premium = upload_cache_key(digest, SegmentationMode.GPT_5_6_LAYOUT)

        self.assertEqual(len(standard), 64)
        self.assertNotEqual(standard, premium)

    def test_provider_model_is_server_controlled(self):
        with patch.dict(
            os.environ,
            {"PANEL_LLM_MODEL": "provider/server-selected-model"},
        ):
            standard = detector_options_for(SegmentationMode.STANDARD)
            premium = detector_options_for(SegmentationMode.GPT_5_6_LAYOUT)

        self.assertEqual(standard["panel_llm_mode"], "off")
        self.assertNotIn("panel_llm_model", standard)
        self.assertEqual(premium["panel_llm_mode"], "always")
        self.assertEqual(
            premium["panel_llm_model"],
            "provider/server-selected-model",
        )

    def test_metadata_records_mode_and_access_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            result_directory = Path(directory)
            write_metadata(
                result_directory,
                SegmentationMode.GPT_5_6_LAYOUT,
            )

            self.assertEqual(
                read_metadata(result_directory),
                {
                    "segmentation_mode": "gpt-5.6-layout",
                    "access_policy": "authenticated",
                },
            )

    def test_legacy_result_without_metadata_is_public_standard(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                read_metadata(Path(directory)),
                {
                    "segmentation_mode": "standard",
                    "access_policy": "public",
                },
            )

    def test_metadata_rejects_policy_that_does_not_match_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata_path = Path(directory) / "metadata.json"
            metadata_path.write_text(json.dumps({
                "segmentation_mode": "gpt-5.6-layout",
                "access_policy": "public",
            }))

            with self.assertRaises(ValueError):
                read_metadata(Path(directory))


if __name__ == "__main__":
    unittest.main()
