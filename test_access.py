import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

import app
from chapter_contract import SegmentationMode, write_metadata


class ChapterCreationAccessTest(unittest.IsolatedAsyncioTestCase):
    async def test_standard_creation_access_matrix_skips_billing(self):
        for user_id in (None, "free_user", "pro_user"):
            with self.subTest(user_id=user_id), patch(
                "app.require_active_subscription",
            ) as require_subscription:
                await app.authorize_creation(SegmentationMode.STANDARD, user_id)
                require_subscription.assert_not_called()

    async def test_anonymous_premium_creation_requires_sign_in(self):
        with self.assertRaises(HTTPException) as raised:
            await app.authorize_creation(
                SegmentationMode.GPT_5_6_LAYOUT,
                None,
            )

        self.assertEqual(raised.exception.status_code, 401)
        self.assertEqual(raised.exception.detail["code"], "sign_in_required")

    async def test_free_premium_creation_requires_subscription(self):
        rejection = HTTPException(
            status_code=402,
            detail={
                "code": "subscription_required",
                "message": "Pro is required.",
            },
        )
        with patch(
            "app.run_in_threadpool",
            new=AsyncMock(side_effect=rejection),
        ):
            with self.assertRaises(HTTPException) as raised:
                await app.authorize_creation(
                    SegmentationMode.GPT_5_6_LAYOUT,
                    "free_user",
                )

        self.assertEqual(raised.exception.detail["code"], "subscription_required")

    async def test_pro_premium_creation_is_allowed(self):
        threadpool = AsyncMock(return_value=None)
        with patch("app.run_in_threadpool", new=threadpool):
            await app.authorize_creation(
                SegmentationMode.GPT_5_6_LAYOUT,
                "pro_user",
            )

        threadpool.assert_awaited_once_with(
            app.require_active_subscription,
            "pro_user",
        )

    async def test_rejected_premium_request_never_starts_extraction(self):
        data = app.Data(
            chapter_url="https://opchapters.com/chapter/one",
            segmentation_mode=SegmentationMode.GPT_5_6_LAYOUT,
        )
        with patch(
            "app.authorize_creation",
            new=AsyncMock(side_effect=HTTPException(
                status_code=402,
                detail={
                    "code": "subscription_required",
                    "message": "Pro is required.",
                },
            )),
        ), patch("app.run_extraction") as extraction:
            with self.assertRaises(HTTPException):
                await app.post_chapter_v2(data, "free_user")

        extraction.assert_not_called()


class ChapterRetrievalAccessTest(unittest.TestCase):
    def test_standard_and_legacy_results_are_public(self):
        for user_id in (None, "free_user", "pro_user"):
            with self.subTest(user_id=user_id):
                app.authorize_retrieval(
                    {
                        "segmentation_mode": "standard",
                        "access_policy": "public",
                    },
                    user_id,
                )

    def test_premium_result_requires_account_but_not_subscription(self):
        metadata = {
            "segmentation_mode": "gpt-5.6-layout",
            "access_policy": "authenticated",
        }
        with self.assertRaises(HTTPException) as raised:
            app.authorize_retrieval(metadata, None)
        self.assertEqual(raised.exception.detail["code"], "sign_in_required")

        app.authorize_retrieval(metadata, "free_user")
        app.authorize_retrieval(metadata, "pro_user")

    def test_get_premium_result_does_not_consult_stripe(self):
        with tempfile.TemporaryDirectory() as directory:
            jsons_directory = Path(directory)
            result_directory = jsons_directory / "premium_hash"
            result_directory.mkdir()
            (result_directory / "kumiko.json").write_text(
                json.dumps({"pages": []}),
            )
            write_metadata(
                result_directory,
                SegmentationMode.GPT_5_6_LAYOUT,
            )

            with patch.object(app, "JSONS_DIR", jsons_directory), patch(
                "app.require_active_subscription",
            ) as require_subscription:
                import asyncio
                result = asyncio.run(app.get_chapter("premium_hash", "free_user"))

            self.assertEqual(result, {"pages": []})
            require_subscription.assert_not_called()
