"""
InsureIQ — Upload Validation Utility
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Single source of truth for validating an uploaded document *before* it enters
the pipeline. Used by the FastAPI `/analyze` endpoint (HTTP path).

Checks, in order:
  1. Extension — must be pdf or docx
  2. Non-empty — reject zero-byte uploads
  3. Size — must be <= MAX_FILE_SIZE_BYTES
  4. Magic bytes — file *content* must match the claimed extension
     (blocks disguised uploads, e.g. an .exe renamed to .pdf)

This is a pure utility — no LLM calls, no I/O, nothing written to disk. Every
failure raises ValueError with a user-safe message the API surfaces as HTTP 400.
"""

from pathlib import Path

from config.settings import settings

# ─── Magic bytes for content-based type validation ────────────────────────────
# Validates the actual file content, not just the filename extension.
PDF_MAGIC_BYTES = b"%PDF"
DOCX_MAGIC_BYTES = b"PK\x03\x04"  # ZIP header — DOCX is a ZIP archive


def _magic_bytes_match(file_bytes: bytes, extension: str) -> bool:
    """Return True if the file's leading bytes match the claimed extension."""
    if extension == "pdf":
        return file_bytes[:4] == PDF_MAGIC_BYTES
    if extension == "docx":
        return file_bytes[:4] == DOCX_MAGIC_BYTES
    return False


def validate_upload(file_bytes: bytes, filename: str) -> str:
    """
    Validate an uploaded document before pipeline processing.

    Args:
        file_bytes: Raw uploaded bytes (already in memory)
        filename: Original filename (used for extension detection)

    Returns:
        The normalized lowercase extension ("pdf" or "docx")

    Raises:
        ValueError: On any validation failure, with a user-safe message.
    """
    extension = Path(filename or "").suffix.lower().lstrip(".")

    if extension not in settings.ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '.{extension}'. "
            "InsureIQ accepts PDF and DOCX files only."
        )

    if len(file_bytes) == 0:
        raise ValueError("Uploaded file is empty.")

    if len(file_bytes) > settings.MAX_FILE_SIZE_BYTES:
        size_mb = len(file_bytes) / (1024 * 1024)
        raise ValueError(
            f"File size {size_mb:.1f} MB exceeds the "
            f"{settings.MAX_FILE_SIZE_MB} MB limit."
        )

    if not _magic_bytes_match(file_bytes, extension):
        raise ValueError(
            f"File content does not match the declared type (.{extension}). "
            "The file may be corrupted or misnamed."
        )

    return extension
