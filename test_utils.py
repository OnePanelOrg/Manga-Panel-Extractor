import os
import tempfile
import unittest

from utils import list_files, name_requirements


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


if __name__ == "__main__":
    unittest.main()
