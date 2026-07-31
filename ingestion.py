"""Turn uploaded comic files into a safe, canonical ordered page set."""

from __future__ import annotations

import hashlib
import io
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Sequence

import pypdfium2 as pdfium
import rarfile
from PIL import Image, ImageOps, UnidentifiedImageError


SUPPORTED_IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
SUPPORTED_CONTAINER_EXTENSIONS = {".cbz", ".cbr", ".zip", ".rar", ".pdf"}
SUPPORTED_UPLOAD_EXTENSIONS = SUPPORTED_IMAGE_EXTENSIONS | SUPPORTED_CONTAINER_EXTENSIONS

MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", 250 * 1024 * 1024))
MAX_EXPANDED_BYTES = int(os.environ.get("MAX_EXPANDED_BYTES", 750 * 1024 * 1024))
MAX_PAGE_BYTES = int(os.environ.get("MAX_PAGE_BYTES", 40 * 1024 * 1024))
MAX_PAGES = int(os.environ.get("MAX_CHAPTER_IMAGES", 100))
MAX_IMAGE_PIXELS = int(os.environ.get("MAX_IMAGE_PIXELS", 40_000_000))
MAX_ARCHIVE_RATIO = int(os.environ.get("MAX_ARCHIVE_RATIO", 250))
COPY_CHUNK_BYTES = 1024 * 1024


class IngestionError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class UploadSource:
    filename: str
    stream: BinaryIO


@dataclass
class IngestedChapter:
    directory: Path
    content_digest: str
    page_names: list[str]

    def cleanup(self) -> None:
        shutil.rmtree(self.directory.parent, ignore_errors=True)


def natural_sort_key(value: str) -> list[tuple[int, object]]:
    return [
        (1, int(part)) if part.isdigit() else (0, part.casefold())
        for part in re.split(r"(\d+)", value.replace("\\", "/"))
    ]


def supported_upload(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_UPLOAD_EXTENSIONS


def _safe_filename(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    return normalized.rsplit("/", 1)[-1]


def _copy_limited(source: BinaryIO, destination: BinaryIO, maximum: int) -> int:
    total = 0
    while True:
        chunk = source.read(COPY_CHUNK_BYTES)
        if not chunk:
            return total
        total += len(chunk)
        if total > maximum:
            raise IngestionError(
                f"Upload exceeds the {maximum // (1024 * 1024)} MB limit.",
                413,
            )
        destination.write(chunk)


def _read_limited(source: BinaryIO, maximum: int, label: str) -> bytes:
    output = io.BytesIO()
    try:
        _copy_limited(source, output, maximum)
    except IngestionError as error:
        raise IngestionError(f"{label} exceeds the size limit.", 413) from error
    return output.getvalue()


def _zip_pages(path: Path) -> list[tuple[str, bytes]]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        raise IngestionError("The ZIP/CBZ file is invalid or damaged.") from error

    pages: list[tuple[str, bytes]] = []
    expanded = 0
    with archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir()
            and Path(member.filename).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
            and "__MACOSX/" not in member.filename.replace("\\", "/")
        ]
        members.sort(key=lambda member: natural_sort_key(member.filename))
        _validate_page_count(len(members))
        for member in members:
            expanded += member.file_size
            if expanded > MAX_EXPANDED_BYTES:
                raise IngestionError("The archive expands beyond the safety limit.", 413)
            if member.file_size > MAX_PAGE_BYTES:
                raise IngestionError(f"{member.filename} exceeds the page size limit.", 413)
            if (
                member.compress_size > 0
                and member.file_size / member.compress_size > MAX_ARCHIVE_RATIO
            ):
                raise IngestionError("The archive has an unsafe compression ratio.", 400)
            with archive.open(member) as page:
                pages.append((
                    _safe_filename(member.filename),
                    _read_limited(page, MAX_PAGE_BYTES, member.filename),
                ))
    return pages


def _rar_pages(path: Path) -> list[tuple[str, bytes]]:
    try:
        archive = rarfile.RarFile(path)
        members = [
            member
            for member in archive.infolist()
            if not member.isdir()
            and Path(member.filename).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
            and "__MACOSX/" not in member.filename.replace("\\", "/")
        ]
        members.sort(key=lambda member: natural_sort_key(member.filename))
        _validate_page_count(len(members))
        pages: list[tuple[str, bytes]] = []
        expanded = 0
        with archive:
            for member in members:
                expanded += member.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise IngestionError(
                        "The archive expands beyond the safety limit.",
                        413,
                    )
                if member.file_size > MAX_PAGE_BYTES:
                    raise IngestionError(
                        f"{member.filename} exceeds the page size limit.",
                        413,
                    )
                if (
                    member.compress_size > 0
                    and member.file_size / member.compress_size > MAX_ARCHIVE_RATIO
                ):
                    raise IngestionError(
                        "The archive has an unsafe compression ratio.",
                        400,
                    )
                with archive.open(member) as page:
                    pages.append((
                        _safe_filename(member.filename),
                        _read_limited(page, MAX_PAGE_BYTES, member.filename),
                    ))
        return pages
    except IngestionError:
        raise
    except rarfile.NeedFirstVolume as error:
        raise IngestionError("Multi-volume RAR/CBR files are not supported.") from error
    except (rarfile.Error, OSError) as error:
        raise IngestionError(
            "The RAR/CBR file is invalid, damaged, or uses an unsupported variant."
        ) from error


def _pdf_pages(path: Path) -> list[tuple[str, bytes]]:
    try:
        document = pdfium.PdfDocument(path)
    except Exception as error:
        raise IngestionError("The PDF file is invalid, damaged, or encrypted.") from error

    try:
        _validate_page_count(len(document))
        pages = []
        expanded = 0
        for index in range(len(document)):
            page = document[index]
            try:
                width, height = page.get_size()
                if width * height * 4 > MAX_IMAGE_PIXELS:
                    raise IngestionError(
                        f"PDF page {index + 1} exceeds the pixel limit.",
                        413,
                    )
                bitmap = page.render(scale=2)
                image = bitmap.to_pil()
                output = io.BytesIO()
                image.save(output, format="PNG", optimize=True)
                data = output.getvalue()
                expanded += len(data)
                if len(data) > MAX_PAGE_BYTES or expanded > MAX_EXPANDED_BYTES:
                    raise IngestionError(
                        "The rendered PDF exceeds the expanded size limit.",
                        413,
                    )
                pages.append((f"page-{index + 1:04d}.png", data))
            finally:
                page.close()
        return pages
    except IngestionError:
        raise
    except Exception as error:
        raise IngestionError("The PDF could not be converted into page images.") from error
    finally:
        document.close()


def _validate_page_count(count: int) -> None:
    if count == 0:
        raise IngestionError("No supported page images were found.")
    if count > MAX_PAGES:
        raise IngestionError(f"A chapter can contain at most {MAX_PAGES} pages.", 413)


def _canonicalize_page(data: bytes, destination: Path) -> bytes:
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.seek(0)
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise IngestionError(
                    f"A page exceeds the {MAX_IMAGE_PIXELS:,}-pixel limit.",
                    413,
                )
            image = ImageOps.exif_transpose(source).convert("RGB")
            if image.width < 1 or image.height < 1:
                raise IngestionError("A page image has invalid dimensions.")
            pixel_count = image.width * image.height
            if pixel_count > MAX_IMAGE_PIXELS:
                raise IngestionError(
                    f"A page exceeds the {MAX_IMAGE_PIXELS:,}-pixel limit.",
                    413,
                )

            digest = hashlib.sha256()
            digest.update(image.width.to_bytes(4, "big"))
            digest.update(image.height.to_bytes(4, "big"))
            digest.update(image.tobytes())
            image.save(destination, format="WEBP", lossless=True, method=4)
            return digest.digest()
    except IngestionError:
        raise
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as error:
        raise IngestionError("A page is not a valid supported image.") from error


def _raw_pages(
    staged: Sequence[tuple[str, Path]],
) -> list[tuple[str, bytes]]:
    pages = []
    for filename, path in sorted(staged, key=lambda item: natural_sort_key(item[0])):
        with path.open("rb") as page:
            pages.append((
                _safe_filename(filename),
                _read_limited(page, MAX_PAGE_BYTES, filename),
            ))
    _validate_page_count(len(pages))
    return pages


def ingest_uploads(sources: Iterable[UploadSource]) -> IngestedChapter:
    """Ingest one container/PDF or an ordered set of loose page images."""

    working_directory = Path(tempfile.mkdtemp(prefix="onepanel-upload-"))
    staged: list[tuple[str, Path]] = []
    total_upload_bytes = 0
    try:
        for index, source in enumerate(sources):
            filename = _safe_filename(source.filename)
            extension = Path(filename).suffix.lower()
            if extension not in SUPPORTED_UPLOAD_EXTENSIONS:
                raise IngestionError(f"{filename or 'File'} has an unsupported format.")
            staged_path = working_directory / f"upload-{index:04d}{extension}"
            with staged_path.open("wb") as output:
                remaining = MAX_UPLOAD_BYTES - total_upload_bytes
                if remaining <= 0:
                    raise IngestionError("Uploads exceed the total size limit.", 413)
                total_upload_bytes += _copy_limited(source.stream, output, remaining)
            staged.append((filename, staged_path))

        if not staged:
            raise IngestionError("Choose at least one file to upload.")

        container_files = [
            item
            for item in staged
            if Path(item[0]).suffix.lower() in SUPPORTED_CONTAINER_EXTENSIONS
        ]
        if container_files and len(staged) != 1:
            raise IngestionError(
                "Upload one archive or PDF at a time, or select page images only."
            )

        if container_files:
            filename, path = container_files[0]
            extension = Path(filename).suffix.lower()
            if extension in {".zip", ".cbz"}:
                raw_pages = _zip_pages(path)
            elif extension in {".rar", ".cbr"}:
                raw_pages = _rar_pages(path)
            else:
                raw_pages = _pdf_pages(path)
        else:
            raw_pages = _raw_pages(staged)

        pages_directory = working_directory / "pages"
        pages_directory.mkdir()
        chapter_digest = hashlib.sha256()
        page_names = []
        for index, (_, data) in enumerate(raw_pages, start=1):
            page_name = f"{index:04d}.webp"
            page_digest = _canonicalize_page(data, pages_directory / page_name)
            chapter_digest.update(index.to_bytes(4, "big"))
            chapter_digest.update(page_digest)
            page_names.append(page_name)

        return IngestedChapter(
            directory=pages_directory,
            content_digest=chapter_digest.hexdigest(),
            page_names=page_names,
        )
    except Exception:
        shutil.rmtree(working_directory, ignore_errors=True)
        raise
