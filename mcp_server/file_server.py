"""
InsureIQ — MCP File Server
━━━━━━━━━━━━━━━━━━━━━━━━━
Custom MCP server built with the mcp Python SDK.
Handles file ingestion as the entry point to the InsureIQ pipeline.

Responsibilities:
  - Accept PDF and DOCX file uploads
  - Validate file type (reject anything that isn't PDF/DOCX)
  - Validate file size (reject > 50 MB)
  - Return file bytes and metadata to the calling agent
  - Never write uploaded documents to disk

Kaggle concept demonstrated: MCP Server integration

Security:
  - Files are held in memory during processing only
  - No persistence of user documents
  - File type validated by both extension AND magic bytes
  - Malformed files rejected with clear error messages
"""

import logging
import io
from typing import Annotated

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from config.settings import settings

logger = logging.getLogger(__name__)

# ─── Magic bytes for file type validation ─────────────────────────────────────
# Validates actual file content, not just filename extension.
# Prevents disguised files (e.g., a .exe renamed to .pdf)
PDF_MAGIC_BYTES = b"%PDF"
DOCX_MAGIC_BYTES = b"PK\x03\x04"  # ZIP header — DOCX is a ZIP archive


def _validate_magic_bytes(file_bytes: bytes, claimed_extension: str) -> bool:
    """
    Verify file content matches claimed type via magic bytes.

    Args:
        file_bytes: Raw file content
        claimed_extension: Extension from filename ("pdf" or "docx")

    Returns:
        True if magic bytes match, False otherwise
    """
    if claimed_extension == "pdf":
        return file_bytes[:4] == PDF_MAGIC_BYTES
    elif claimed_extension == "docx":
        return file_bytes[:4] == DOCX_MAGIC_BYTES
    return False


# ─── MCP Server Setup ─────────────────────────────────────────────────────────

app = Server("insureiq-file-server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Declare available MCP tools to the ADK agent runtime."""
    return [
        Tool(
            name="upload_insurance_document",
            description=(
                "Upload an insurance document (PDF or DOCX) for analysis. "
                "Returns extracted file bytes and metadata. "
                "Files are processed in memory and never stored on disk."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Original filename including extension (e.g., policy.pdf)",
                    },
                    "file_content_hex": {
                        "type": "string",
                        "description": "Hex-encoded file bytes (convert binary to hex before sending)",
                    },
                },
                "required": ["filename", "file_content_hex"],
            },
        ),
        Tool(
            name="validate_document",
            description=(
                "Validate an insurance document without processing it. "
                "Returns validation status and detected file properties."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "file_size_bytes": {"type": "integer"},
                },
                "required": ["filename", "file_size_bytes"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """
    Route MCP tool calls to the appropriate handler.

    Args:
        name: Tool name from list_tools()
        arguments: Tool input arguments

    Returns:
        List of TextContent with result or error message
    """
    if name == "upload_insurance_document":
        return await _handle_upload(arguments)
    elif name == "validate_document":
        return await _handle_validate(arguments)
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def _handle_upload(arguments: dict) -> list[TextContent]:
    """
    Handle document upload: decode, validate, and return bytes for pipeline.

    Security checks (in order):
    1. Filename extension must be pdf or docx
    2. File size must be <= MAX_FILE_SIZE_BYTES
    3. Magic bytes must match claimed extension
    4. File must be non-empty after all checks pass

    Args:
        arguments: Dict with "filename" and "file_content_hex"

    Returns:
        TextContent with JSON result or error message
    """
    import json

    filename = arguments.get("filename", "")
    file_hex = arguments.get("file_content_hex", "")

    # ── Validate filename ─────────────────────────────────────────────────────
    if not filename:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error": "filename is required"
        }))]

    from pathlib import Path
    extension = Path(filename).suffix.lower().lstrip(".")

    if extension not in settings.ALLOWED_EXTENSIONS:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error": f"File type '.{extension}' is not supported. Upload PDF or DOCX files only."
        }))]

    # ── Decode hex to bytes ───────────────────────────────────────────────────
    try:
        file_bytes = bytes.fromhex(file_hex)
    except ValueError:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error": "Invalid file encoding. file_content_hex must be valid hex."
        }))]

    # ── Validate file size ────────────────────────────────────────────────────
    if len(file_bytes) > settings.MAX_FILE_SIZE_BYTES:
        size_mb = len(file_bytes) / (1024 * 1024)
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error": f"File size {size_mb:.1f} MB exceeds the {settings.MAX_FILE_SIZE_MB} MB limit."
        }))]

    if len(file_bytes) == 0:
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error": "Uploaded file is empty."
        }))]

    # ── Validate magic bytes ──────────────────────────────────────────────────
    if not _validate_magic_bytes(file_bytes, extension):
        return [TextContent(type="text", text=json.dumps({
            "status": "error",
            "error": (
                f"File content does not match the declared type (.{extension}). "
                "The file may be corrupted or misnamed."
            )
        }))]

    # ── All checks passed ─────────────────────────────────────────────────────
    logger.info(f"MCP file server: accepted {filename} ({len(file_bytes)} bytes)")

    return [TextContent(type="text", text=json.dumps({
        "status": "success",
        "filename": filename,
        "extension": extension,
        "size_bytes": len(file_bytes),
        "size_mb": round(len(file_bytes) / (1024 * 1024), 2),
        # Return hex so ADK can pass it to Ingestion Agent
        "file_content_hex": file_hex,
        "message": f"File '{filename}' accepted and ready for analysis."
    }))]


async def _handle_validate(arguments: dict) -> list[TextContent]:
    """
    Lightweight validation — checks filename and size without processing content.
    Useful for client-side pre-checks before uploading.

    Args:
        arguments: Dict with "filename" and "file_size_bytes"

    Returns:
        TextContent with validation result
    """
    import json
    from pathlib import Path

    filename = arguments.get("filename", "")
    file_size = arguments.get("file_size_bytes", 0)

    extension = Path(filename).suffix.lower().lstrip(".")
    ext_valid = extension in settings.ALLOWED_EXTENSIONS
    size_valid = file_size <= settings.MAX_FILE_SIZE_BYTES

    return [TextContent(type="text", text=json.dumps({
        "filename": filename,
        "extension": extension,
        "extension_valid": ext_valid,
        "size_bytes": file_size,
        "size_mb": round(file_size / (1024 * 1024), 2),
        "size_valid": size_valid,
        "overall_valid": ext_valid and size_valid,
        "errors": [
            *([f"File type '.{extension}' not supported"] if not ext_valid else []),
            *([f"File too large ({file_size / (1024*1024):.1f} MB > {settings.MAX_FILE_SIZE_MB} MB)"] if not size_valid else []),
        ]
    }))]


async def run_mcp_server():
    """Start the MCP server using stdio transport."""
    logger.info(f"Starting InsureIQ MCP file server...")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=settings.LOG_LEVEL)
    asyncio.run(run_mcp_server())
