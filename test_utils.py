import os
import tempfile
import unittest

from utils import list_files, name_requirements
from kumikolib import Kumiko, natural_sort_key, page_sort_key


class ImageSourceTests(unittest.TestCase):
    def test_accepts_supported_op_chapters_images(self):
        self.assertTrue(name_requirements("https://i.example/chapter/page.png"))
        self.assertTrue(name_requirements("https://i.example/chapter/page.webp"))
        self.assertTrue(
            name_requirements("https://i.example/chapter/PAGE.WEBP?width=1200")
        )

    def test_rejects_unsupported_sources(self):
        self.assertFalse(name_requirements(None))
        self.assertFalse(name_requirements("/chapter/page.webp"))
        self.assertFalse(name_requirements("https://cdn.example/chapter/page.webp"))
        self.assertFalse(name_requirements("https://i.example/chapter/page.jpg"))

    def test_scanner_includes_webp(self):
        with tempfile.TemporaryDirectory() as directory:
            webp_path = os.path.join(directory, "page.webp")
            text_path = os.path.join(directory, "notes.txt")
            open(webp_path, "wb").close()
            open(text_path, "w").close()

            images, _, text_files = list_files(directory)

            self.assertEqual(images, [webp_path])
            self.assertEqual(text_files, [text_path])


class PageOrderTests(unittest.TestCase):
    def test_natural_sort_preserves_numeric_page_order(self):
        filenames = [
            "10.webp",
            "12.webp",
            "14.webp",
            "15.webp",
            "16.webp",
            "1.webp",
            "2.webp",
            "3.webp",
            "4.webp",
            "6.webp",
            "8.webp",
            "9.webp",
        ]

        self.assertEqual(
            sorted(filenames, key=natural_sort_key),
            [
                "1.webp",
                "2.webp",
                "3.webp",
                "4.webp",
                "6.webp",
                "8.webp",
                "9.webp",
                "10.webp",
                "12.webp",
                "14.webp",
                "15.webp",
                "16.webp",
            ],
        )

    def test_explicit_page_index_takes_precedence(self):
        pages = [
            {"filename": "1.webp", "pageIndex": 2},
            {"filename": "10.webp", "pageIndex": 1},
        ]

        self.assertEqual(
            [page["filename"] for page in sorted(pages, key=page_sort_key)],
            ["10.webp", "1.webp"],
        )

    def test_parse_images_uses_natural_order_for_legacy_downloads(self):
        filenames = [
            "10.webp",
            "12.webp",
            "1.webp",
            "2.webp",
            "9.webp",
        ]
        kumiko = Kumiko()
        kumiko.parse_image = lambda filename, _: {"filename": filename}

        pages = kumiko.parse_images(
            filenames,
            {filename: f"https://images.example/{filename}" for filename in filenames},
        )

        self.assertEqual(
            [page["filename"] for page in pages],
            ["1.webp", "2.webp", "9.webp", "10.webp", "12.webp"],
        )


if __name__ == "__main__":
    unittest.main()
