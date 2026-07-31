import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from ingestion import IngestionError, UploadSource, ingest_uploads, natural_sort_key


def image_bytes(colour, image_format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (24, 32), colour).save(output, format=image_format)
    return output.getvalue()


def zip_bytes(entries):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return output.getvalue()


class UploadIngestionTest(unittest.TestCase):
    def test_loose_images_are_naturally_sorted_and_normalized(self):
        chapter = ingest_uploads([
            UploadSource("10.jpg", io.BytesIO(image_bytes("red", "JPEG"))),
            UploadSource("2.png", io.BytesIO(image_bytes("blue"))),
        ])
        self.addCleanup(chapter.cleanup)

        self.assertEqual(chapter.page_names, ["0001.webp", "0002.webp"])
        with Image.open(chapter.directory / "0001.webp") as first:
            self.assertEqual(first.getpixel((0, 0)), (0, 0, 255))

    def test_container_metadata_does_not_change_content_identity(self):
        pages = [
            ("Comic/1.png", image_bytes("white")),
            ("Comic/2.png", image_bytes("black")),
        ]
        first = ingest_uploads([
            UploadSource("chapter.cbz", io.BytesIO(zip_bytes(pages))),
        ])
        second = ingest_uploads([
            UploadSource(
                "chapter.zip",
                io.BytesIO(zip_bytes([("notes.txt", b"ignored"), *pages])),
            ),
        ])
        self.addCleanup(first.cleanup)
        self.addCleanup(second.cleanup)

        self.assertEqual(first.content_digest, second.content_digest)

    def test_equivalent_pixel_data_has_the_same_identity_across_image_formats(self):
        png = ingest_uploads([
            UploadSource("1.png", io.BytesIO(image_bytes("red", "PNG"))),
        ])
        bmp = ingest_uploads([
            UploadSource("1.bmp", io.BytesIO(image_bytes("red", "BMP"))),
        ])
        self.addCleanup(png.cleanup)
        self.addCleanup(bmp.cleanup)

        self.assertEqual(png.content_digest, bmp.content_digest)

    def test_pdf_pages_are_rasterized_in_document_order(self):
        pdf = io.BytesIO()
        images = [
            Image.new("RGB", (24, 32), "red"),
            Image.new("RGB", (24, 32), "blue"),
        ]
        images[0].save(pdf, format="PDF", save_all=True, append_images=images[1:])

        chapter = ingest_uploads([
            UploadSource("chapter.pdf", io.BytesIO(pdf.getvalue())),
        ])
        self.addCleanup(chapter.cleanup)

        self.assertEqual(chapter.page_names, ["0001.webp", "0002.webp"])

    def test_rejects_mixed_containers_and_images(self):
        with self.assertRaisesRegex(IngestionError, "one archive or PDF"):
            ingest_uploads([
                UploadSource("chapter.cbz", io.BytesIO(zip_bytes([
                    ("1.png", image_bytes("white")),
                ]))),
                UploadSource("cover.png", io.BytesIO(image_bytes("white"))),
            ])

    def test_rejects_archives_without_pages(self):
        with self.assertRaisesRegex(IngestionError, "No supported page images"):
            ingest_uploads([
                UploadSource(
                    "chapter.cbz",
                    io.BytesIO(zip_bytes([("README.txt", b"hello")])),
                ),
            ])

    def test_enforces_page_count_limit_before_extraction(self):
        archive = zip_bytes([
            (f"{index}.png", image_bytes("white"))
            for index in range(3)
        ])
        with patch("ingestion.MAX_PAGES", 2):
            with self.assertRaisesRegex(IngestionError, "at most 2 pages"):
                ingest_uploads([
                    UploadSource("chapter.cbz", io.BytesIO(archive)),
                ])

    def test_natural_sort_handles_nested_numeric_names(self):
        names = ["book/10.png", "book/2.png", "book/1.png"]
        self.assertEqual(
            sorted(names, key=natural_sort_key),
            ["book/1.png", "book/2.png", "book/10.png"],
        )


if __name__ == "__main__":
    unittest.main()
