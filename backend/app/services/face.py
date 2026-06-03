from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import get_settings

log = logging.getLogger("secureconnect.face")
_settings = get_settings()


@dataclass
class FaceResult:
    verified: bool
    confidence: float | None
    distance: float | None
    threshold: float | None
    detail: str | None = None


def _stub_result() -> FaceResult:
    return FaceResult(
        verified=False,
        confidence=None,
        distance=None,
        threshold=None,
        detail="Face verification is disabled on this build.",
    )


def preload_model() -> None:
    if not _settings.deepface_enabled:
        log.info("deepface_disabled")
        return
    try:
        from deepface import DeepFace  # heavy import deferred

        DeepFace.build_model("VGG-Face")
        log.info("deepface_model_loaded")
    except Exception as exc:  # pragma: no cover — environment dependent
        log.warning("deepface_preload_failed: %s", exc)


def verify_faces(id_path: str, selfie_path: str) -> FaceResult:
    """Wraps DeepFace.verify with a normalised response and safe error handling.

    Never raises — encodes failures as `verified=False` with a generic detail
    so the API can return a sanitized message without leaking internals.
    """
    if not _settings.deepface_enabled:
        return _stub_result()

    try:
        from deepface import DeepFace
    except ImportError:
        return FaceResult(
            verified=False,
            confidence=None,
            distance=None,
            threshold=None,
            detail="Face verification dependencies unavailable.",
        )

    try:
        result = DeepFace.verify(
            img1_path=id_path,
            img2_path=selfie_path,
            enforce_detection=True,
            anti_spoofing=True,
        )
    except Exception as exc:
        log.warning("deepface_verify_failed: %s", type(exc).__name__)
        return FaceResult(
            verified=False,
            confidence=None,
            distance=None,
            threshold=None,
            detail="Could not detect a face in one of the images.",
        )

    return FaceResult(
        verified=bool(result.get("verified", False)),
        confidence=_safe_float(result.get("confidence")),
        distance=_safe_float(result.get("distance")),
        threshold=_safe_float(result.get("threshold")),
        detail=None if result.get("verified") else "Faces do not match closely enough.",
    )


def _safe_float(v) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
