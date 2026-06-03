import io
import os

import pytest
from starlette.datastructures import Headers, UploadFile

from backend.app.errors import TooLarge, UploadInvalid
from backend.app.services.uploads import save_image_safely


# Minimal valid JPG bytes (SOI + APP0 + ~64 bytes of dummy data + EOI).
JPG_PREFIX = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
PNG_PREFIX = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


def _upload(content: bytes, filename: str = "doesntmatter.jpg") -> UploadFile:
    headers = Headers({"content-type": "application/octet-stream"})
    return UploadFile(filename=filename, file=io.BytesIO(content), headers=headers)


@pytest.mark.asyncio
async def test_accepts_jpg():
    saved = await save_image_safely(_upload(JPG_PREFIX + b"\x00" * 256))
    try:
        assert saved.mime == "image/jpeg"
        assert os.path.exists(saved.path)
        # The client filename must not appear anywhere in the saved path.
        assert "doesntmatter" not in saved.path
    finally:
        saved.cleanup()
        assert not os.path.exists(saved.path)


@pytest.mark.asyncio
async def test_accepts_png():
    saved = await save_image_safely(_upload(PNG_PREFIX))
    try:
        assert saved.mime == "image/png"
    finally:
        saved.cleanup()


@pytest.mark.asyncio
async def test_rejects_non_image():
    with pytest.raises(UploadInvalid):
        await save_image_safely(_upload(b"not-an-image" * 10))


@pytest.mark.asyncio
async def test_rejects_oversized(monkeypatch):
    # MAX_UPLOAD_BYTES is 2MB in tests (set in conftest). Push past that.
    big = JPG_PREFIX + b"\x00" * (3 * 1024 * 1024)
    with pytest.raises(TooLarge):
        await save_image_safely(_upload(big))


@pytest.mark.asyncio
async def test_rejects_tiny_file():
    # Header passes magic check but the file is too small to be a real image.
    with pytest.raises(UploadInvalid):
        await save_image_safely(_upload(b"\xff\xd8\xff"))


@pytest.mark.asyncio
async def test_path_traversal_filename_ignored():
    """A malicious filename must not influence the saved path."""
    upload = _upload(JPG_PREFIX + b"\x00" * 256, filename="../../etc/passwd")
    saved = await save_image_safely(upload)
    try:
        assert "etc" not in saved.path
        assert "passwd" not in saved.path
        assert ".." not in saved.path
    finally:
        saved.cleanup()
