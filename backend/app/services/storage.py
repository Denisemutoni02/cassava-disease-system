"""Image upload storage and validation helpers."""

import io
import logging
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.config import get_settings

logger = logging.getLogger(__name__)


class ImageValidationError(ValueError):
    """Raised when an uploaded file is not an acceptable leaf photo."""


def validate_and_store(data: bytes, content_type: str) -> Path:
    """Validate image bytes (type, size, decodability) and persist to UPLOAD_DIR.

    Returns the absolute file path. File name is a random UUID to avoid
    collisions and path traversal.
    """
    settings = get_settings()
    allowed = settings.allowed_image_type_list

    if content_type.lower() not in allowed:
        raise ImageValidationError(
            f"Unsupported file type '{content_type}'. Allowed: {', '.join(allowed)}."
        )

    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise ImageValidationError(
            f"Image is too large ({len(data) / 1024 / 1024:.1f} MB). "
            f"Maximum allowed is {settings.max_upload_mb} MB."
        )
    if len(data) < 1024:
        raise ImageValidationError("Image file is too small or corrupted. Please retake the photo.")

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()  # structural check
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            img.load()  # force full decode
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageValidationError("The file could not be decoded as an image. Please retake or re-upload.") from exc

    if width < 64 or height < 64:
        raise ImageValidationError(
            f"Image resolution is too low ({width}×{height}). Minimum is 64×64 pixels."
        )

    upload_dir: Path = settings.upload_path
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(
        content_type.lower(), ".jpg"
    )
    dest = upload_dir / f"{uuid.uuid4().hex}{ext}"
    dest.write_bytes(data)
    logger.info("Stored upload %s (%d bytes, %d×%d)", dest.name, len(data), width, height)
    return dest
