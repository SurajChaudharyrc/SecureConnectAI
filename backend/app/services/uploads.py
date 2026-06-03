from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from fastapi import UploadFile

from ..config import get_settings
from ..errors import TooLarge, UploadInvalid

_settings = get_settings()

# Magic-byte signatures we accept.
_IMAGE_SIGS: dict[str, tuple[bytes, ...]] = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),  # also requires WEBP at offset 8
}


@dataclass
class SavedImage:
    path: str
    mime: str
    size: int

    def cleanup(self) -> None:
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except OSError:
            pass


def _detect_mime(head: bytes) -> str | None:
    if head.startswith(_IMAGE_SIGS["image/jpeg"][0]):
        return "image/jpeg"
    if head.startswith(_IMAGE_SIGS["image/png"][0]):
        return "image/png"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    return None


_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


async def save_image_safely(upload: UploadFile) -> SavedImage:
    """Validate magic bytes + size, then save to a freshly-named temp file.

    Discards the client-supplied filename entirely (avoids path traversal).
    """
    head = await upload.read(16)
    mime = _detect_mime(head)
    if mime is None:
        raise UploadInvalid("Unsupported image format. Use JPG, PNG, or WEBP.")

    max_bytes = _settings.max_upload_bytes
    written = 0
    fd, path = tempfile.mkstemp(prefix="sc_", suffix=_EXT[mime])
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(head)
            written += len(head)
            while True:
                chunk = await upload.read(64 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise TooLarge(f"File exceeds {max_bytes // (1024 * 1024)} MB.")
                f.write(chunk)
    except Exception:
        # On any error, scrub the file we started writing.
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    finally:
        await upload.close()

    if written < 64:
        try:
            os.remove(path)
        except OSError:
            pass
        raise UploadInvalid("File is too small to be a real image.")

    return SavedImage(path=path, mime=mime, size=written)
