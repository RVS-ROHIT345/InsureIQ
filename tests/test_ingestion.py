"""
InsureIQ — Tests: Ingestion Agent + Document Parser
Run with: pytest tests/test_ingestion.py -v
"""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from tools.document_parser import (
    detect_file_extension,
    validate_file_size,
)
# Magic-bytes validation lives in the MCP file server (the security boundary),
# not the pure document parser. Local package is named mcp_server/ to avoid
# shadowing the installed `mcp` SDK.
from mcp_server.file_server import _validate_magic_bytes


# ── document_parser tests ─────────────────────────────────────────────────────

class TestDetectFileExtension:
    def test_pdf_extension(self):
        assert detect_file_extension("policy.pdf") == "pdf"

    def test_docx_extension(self):
        assert detect_file_extension("insurance.docx") == "docx"

    def test_uppercase_pdf(self):
        assert detect_file_extension("POLICY.PDF") == "pdf"

    def test_unsupported_extension_raises(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            detect_file_extension("document.txt")

    def test_exe_disguised_raises(self):
        with pytest.raises(ValueError):
            detect_file_extension("malicious.exe")

    def test_no_extension_raises(self):
        with pytest.raises(ValueError):
            detect_file_extension("document")


class TestValidateFileSize:
    def test_within_limit_passes(self):
        # 1 MB file, 50 MB limit — should not raise
        file_bytes = b"x" * (1 * 1024 * 1024)
        validate_file_size(file_bytes, 50 * 1024 * 1024)

    def test_exceeds_limit_raises(self):
        # 51 MB file, 50 MB limit
        file_bytes = b"x" * (51 * 1024 * 1024)
        with pytest.raises(ValueError, match="exceeds"):
            validate_file_size(file_bytes, 50 * 1024 * 1024)

    def test_exact_limit_passes(self):
        max_bytes = 10 * 1024 * 1024
        file_bytes = b"x" * max_bytes
        validate_file_size(file_bytes, max_bytes)


class TestMagicBytesValidation:
    """
    Validates that we check actual file content, not just the filename extension.
    This catches disguised files (e.g., a .exe renamed to .pdf).
    """

    def test_valid_pdf_magic_bytes(self):
        pdf_bytes = b"%PDF-1.4 rest of file..."
        assert _validate_magic_bytes(pdf_bytes, "pdf") is True

    def test_invalid_pdf_magic_bytes(self):
        # ZIP file disguised as PDF
        fake_pdf = b"PK\x03\x04this is actually a zip"
        assert _validate_magic_bytes(fake_pdf, "pdf") is False

    def test_valid_docx_magic_bytes(self):
        # DOCX is a ZIP archive — starts with PK magic bytes
        docx_bytes = b"PK\x03\x04this is a docx"
        assert _validate_magic_bytes(docx_bytes, "docx") is True

    def test_invalid_docx_magic_bytes(self):
        fake_docx = b"GARBAGE not a docx file"
        assert _validate_magic_bytes(fake_docx, "docx") is False

    def test_unknown_extension_returns_false(self):
        assert _validate_magic_bytes(b"anything", "txt") is False


# ── MCP file server tests ─────────────────────────────────────────────────────

class TestMCPFileServer:
    """Integration tests for the MCP file server tool handlers."""

    @pytest.mark.asyncio
    async def test_validate_tool_valid_pdf(self):
        from mcp_server.file_server import _handle_validate
        import json

        result = await _handle_validate({"filename": "policy.pdf", "file_size_bytes": 1000000})
        data = json.loads(result[0].text)

        assert data["overall_valid"] is True
        assert data["extension"] == "pdf"
        assert len(data["errors"]) == 0

    @pytest.mark.asyncio
    async def test_validate_tool_invalid_extension(self):
        from mcp_server.file_server import _handle_validate
        import json

        result = await _handle_validate({"filename": "virus.exe", "file_size_bytes": 1000})
        data = json.loads(result[0].text)

        assert data["overall_valid"] is False
        assert len(data["errors"]) > 0

    @pytest.mark.asyncio
    async def test_validate_tool_file_too_large(self):
        from mcp_server.file_server import _handle_validate
        import json

        big_size = 60 * 1024 * 1024  # 60 MB
        result = await _handle_validate({"filename": "large.pdf", "file_size_bytes": big_size})
        data = json.loads(result[0].text)

        assert data["size_valid"] is False
        assert data["overall_valid"] is False


# ── Ingestion Agent tests (with mocked Gemini) ───────────────────────────────

class TestIngestionAgent:
    """
    Tests for run_ingestion_agent. Mocks Gemini API calls so these
    run without a real API key — safe to run in CI.
    """

    MOCK_GEMINI_RESPONSE = """{
        "document_type": "life",
        "sections": {
            "definitions": "Sum Assured means the guaranteed amount payable...",
            "coverage_terms": "Death benefit payable upon death of life assured...",
            "exclusions": "Suicide within first policy year is excluded...",
            "premium_schedule": "Annual premium of ₹12,000 due on 1st January...",
            "maturity_clause": "Maturity benefit of ₹5,00,000 payable on 2044-01-01...",
            "terms_and_conditions": "Policy lapses if premium not paid within grace period..."
        },
        "raw_text_length": 15000
    }"""

    @patch("agents.ingestion_agent.genai")
    @patch("tools.document_parser.pdfplumber")
    def test_ingestion_with_text_pdf(self, mock_pdfplumber, mock_genai):
        """Test ingestion on a text-based PDF (pdfplumber succeeds)."""
        # Mock pdfplumber to return text
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "LIC Life Insurance Policy Document. Sum Assured ₹5,00,000. Premium ₹12,000 per year. Maturity date January 2044. Death benefit payable. Exclusions: suicide in year 1."
        mock_page.extract_tables.return_value = []
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf

        # Mock Gemini response
        mock_model = MagicMock()
        mock_model.generate_content.return_value.text = self.MOCK_GEMINI_RESPONSE
        mock_genai.GenerativeModel.return_value = mock_model
        mock_genai.configure = MagicMock()

        from agents.ingestion_agent import run_ingestion_agent
        result = run_ingestion_agent(b"%PDF-1.4 fake pdf content", "life_policy.pdf")

        assert result["status"] == "success"
        assert result["document_type"] == "life"
        assert "sections" in result
        assert result["extraction_method"] == "pdfplumber"

    def test_ingestion_rejects_wrong_extension(self):
        from agents.ingestion_agent import run_ingestion_agent
        with pytest.raises(ValueError, match="Unsupported file type"):
            run_ingestion_agent(b"some content", "document.txt")

    def test_ingestion_rejects_oversized_file(self):
        from agents.ingestion_agent import run_ingestion_agent
        big_file = b"x" * (60 * 1024 * 1024)  # 60 MB — over limit
        with pytest.raises(ValueError, match="exceeds"):
            run_ingestion_agent(big_file, "huge.pdf")
