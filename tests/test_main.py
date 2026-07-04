"""
InsureIQ — Tests: FastAPI app (main.py) + upload validation
Run with: pytest tests/test_main.py -v

The pipeline is mocked, so these run without a real Gemini key and make no API
calls — they exercise the HTTP layer only: routing, upload validation (extension,
empty, size, magic bytes), error-code mapping, security headers, and CORS.

Note: TestClient is used *without* the `with` context manager on purpose, so the
lifespan startup (which calls settings.validate() and requires GEMINI_API_KEY)
is not triggered — keeping these tests hermetic and CI-safe.
"""

import base64

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

import main
from main import app
from config.settings import settings
from tools.file_validation import validate_upload

client = TestClient(app)

# Minimal byte payloads whose leading (magic) bytes match the claimed type.
# Content beyond the magic bytes is irrelevant here because run_pipeline is mocked.
PDF_BYTES = b"%PDF-1.4\n% fake pdf body for tests"
DOCX_BYTES = b"PK\x03\x04" + b"\x00" * 40

# What the mocked pipeline returns on a successful run.
FAKE_PIPELINE_RESULT = {
    "policy_data": {"policy_number": "POL-1"},
    "coverage_map": {"covered": ["hospitalization"]},
    "financial_verdict": {"verdict": "BREAK_EVEN"},
    "risk_flags": {"overall_risk_level": "MEDIUM", "flags": []},
    "report_intros": {"title": "Your Policy Analysis"},
    "report_bytes": b"PK\x03\x04docx-report-bytes",
    "metadata": {
        "document_type": "life",
        "extraction_method": "pdfplumber",
        "pipeline_duration_seconds": 1.23,
    },
}


def _upload(filename, content, content_type="application/pdf"):
    return client.post("/analyze", files={"file": (filename, content, content_type)})


# ─── Info / health endpoints ──────────────────────────────────────────────────

def test_root_returns_api_info():
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "InsureIQ"
    assert "POST /analyze" in body["endpoints"]
    assert body["max_file_size_mb"] == settings.MAX_FILE_SIZE_MB


def test_health_check():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy", "service": "insureiq"}


def test_security_headers_present():
    resp = client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["Cache-Control"] == "no-store"


def test_cors_headers_present_for_allowed_origin():
    resp = client.get("/health", headers={"Origin": "https://example.com"})
    assert resp.status_code == 200
    # CORSMiddleware echoes the allowed origin (settings default "*").
    assert resp.headers.get("access-control-allow-origin") in {"*", "https://example.com"}


# ─── /analyze — happy path ────────────────────────────────────────────────────

def test_analyze_success_returns_full_payload():
    with patch.object(main, "run_pipeline", return_value=FAKE_PIPELINE_RESULT) as mock_run:
        resp = _upload("policy.pdf", PDF_BYTES)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["filename"] == "policy.pdf"
    assert body["document_type"] == "life"
    assert body["financial_verdict"]["verdict"] == "BREAK_EVEN"
    # Report bytes come back as decodable base64.
    decoded = base64.b64decode(body["report_docx_base64"])
    assert decoded == FAKE_PIPELINE_RESULT["report_bytes"]
    mock_run.assert_called_once()


def test_analyze_success_docx_null_when_no_report_bytes():
    result = {**FAKE_PIPELINE_RESULT, "report_bytes": None}
    with patch.object(main, "run_pipeline", return_value=result):
        resp = _upload("policy.pdf", PDF_BYTES)
    assert resp.status_code == 200
    assert resp.json()["report_docx_base64"] is None


def test_analyze_accepts_docx():
    with patch.object(main, "run_pipeline", return_value=FAKE_PIPELINE_RESULT):
        resp = _upload(
            "policy.docx",
            DOCX_BYTES,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    assert resp.status_code == 200


# ─── /analyze — validation rejections (400, pipeline never called) ────────────

def test_analyze_rejects_bad_extension():
    with patch.object(main, "run_pipeline") as mock_run:
        resp = _upload("notes.txt", b"hello world", "text/plain")
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["detail"]
    mock_run.assert_not_called()


def test_analyze_rejects_empty_file():
    with patch.object(main, "run_pipeline") as mock_run:
        resp = _upload("policy.pdf", b"", "application/pdf")
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()
    mock_run.assert_not_called()


def test_analyze_rejects_magic_byte_mismatch():
    # .pdf extension but the content is not a real PDF (wrong magic bytes).
    with patch.object(main, "run_pipeline") as mock_run:
        resp = _upload("evil.pdf", b"MZ\x90\x00 this is actually an exe", "application/pdf")
    assert resp.status_code == 400
    assert "does not match" in resp.json()["detail"]
    mock_run.assert_not_called()


def test_analyze_rejects_oversized_file(monkeypatch):
    monkeypatch.setattr(settings, "MAX_FILE_SIZE_BYTES", 10)
    with patch.object(main, "run_pipeline") as mock_run:
        resp = _upload("policy.pdf", PDF_BYTES, "application/pdf")
    assert resp.status_code == 400
    assert "limit" in resp.json()["detail"].lower()
    mock_run.assert_not_called()


# ─── /analyze — pipeline error mapping ────────────────────────────────────────

def test_analyze_pipeline_value_error_maps_to_422():
    with patch.object(main, "run_pipeline", side_effect=ValueError("Could not extract text")):
        resp = _upload("policy.pdf", PDF_BYTES)
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Could not extract text"


def test_analyze_internal_error_maps_to_500_without_leaking():
    with patch.object(main, "run_pipeline", side_effect=RuntimeError("gemini exploded: token abc123")):
        resp = _upload("policy.pdf", PDF_BYTES)
    assert resp.status_code == 500
    detail = resp.json()["detail"]
    assert "gemini" not in detail.lower()
    assert "token" not in detail.lower()
    assert "error occurred" in detail.lower()


# ─── validate_upload — unit-level checks ──────────────────────────────────────

def test_validate_upload_returns_normalized_extension():
    assert validate_upload(PDF_BYTES, "Policy.PDF") == "pdf"
    assert validate_upload(DOCX_BYTES, "Policy.DocX") == "docx"


@pytest.mark.parametrize("filename,content,needle", [
    ("a.txt", PDF_BYTES, "Unsupported file type"),
    ("a.pdf", b"", "empty"),
    ("a.pdf", b"not-a-pdf", "does not match"),
    ("a.docx", b"%PDF-1.4", "does not match"),
])
def test_validate_upload_raises_on_bad_input(filename, content, needle):
    with pytest.raises(ValueError) as exc:
        validate_upload(content, filename)
    assert needle.lower() in str(exc.value).lower()
