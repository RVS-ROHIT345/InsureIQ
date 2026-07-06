"""
InsureIQ — FastAPI Entry Point
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Exposes the InsureIQ pipeline via HTTP.

Endpoints:
  POST /analyze  — Upload insurance document, receive analysis
  GET  /health   — Health check (used by Cloud Run)
  GET  /         — API info

Security:
  - File type validated before any processing
  - File size limit enforced at the API layer
  - No document stored on disk — processed in memory and discarded
  - GEMINI_API_KEY loaded from .env, never hardcoded
  - Error responses never expose internal stack traces
"""

import base64
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.settings import settings
from pipeline import run_pipeline
from tools.file_validation import validate_upload
from agents.gemini_utils import GeminiQuotaExhaustedError

# Read the upload in bounded chunks so a malicious/oversized client can never
# force us to buffer more than the limit (+1 byte to detect the overflow) into
# memory, even if the Content-Length header is missing or spoofed.
_READ_CHUNK_SIZE = 1024 * 1024  # 1 MB

# Configure logging early
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup validation — fail fast if config is missing."""
    try:
        settings.validate()
        logger.info("InsureIQ API starting — config validated")
    except EnvironmentError as e:
        logger.critical(f"Startup failed: {e}")
        raise
    yield
    logger.info("InsureIQ API shutting down")


app = FastAPI(
    title="InsureIQ",
    description="AI-powered insurance document analyzer. Upload any insurance PDF or DOCX and receive a plain-English analysis covering coverage, dates, financials, and red flags.",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Origins are configurable via CORS_ALLOWED_ORIGINS ("*" in dev, an explicit
# allow-list in production). We never send credentials, so wildcard is safe.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Attach conservative security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
async def root():
    """API info endpoint."""
    return {
        "name": "InsureIQ",
        "description": "AI-powered insurance document analyzer",
        "version": "1.0.0",
        "endpoints": {
            "POST /analyze": "Upload insurance document and receive full analysis",
            "GET /health": "Health check",
        },
        "supported_formats": ["PDF", "DOCX"],
        "max_file_size_mb": settings.MAX_FILE_SIZE_MB,
    }


@app.get("/health")
async def health_check():
    """Health check — used by Cloud Run and load balancers."""
    return {"status": "healthy", "service": "insureiq"}


@app.post("/analyze")
async def analyze_document(file: UploadFile = File(...)):
    """
    Analyze an insurance document through the full 6-agent pipeline.

    Args:
        file: Uploaded PDF or DOCX insurance document

    Returns:
        JSON analysis result containing:
          - document_type: health | life | car | home
          - policy_data: Extracted policy details
          - coverage_map: What is and isn't covered
          - financial_verdict: ROI analysis and PROFIT/BREAK_EVEN/NET_LOSS verdict
          - risk_flags: Hidden clauses ordered by severity
          - report_docx_base64: The full formatted .docx report, base64-encoded
            (kept inline so nothing is persisted to disk — decode client-side to save)

    Raises:
        400: Invalid file type or size
        422: Document could not be parsed
        500: Internal pipeline error (details not exposed)
    """
    filename = file.filename or "uploaded_document"
    logger.info(f"POST /analyze — received: {filename}")

    # ── Read file into memory (bounded) ───────────────────────────────────────
    # Read in chunks and stop as soon as we exceed the limit, so an oversized or
    # spoofed-Content-Length upload can never make us buffer more than the limit.
    max_bytes = settings.MAX_FILE_SIZE_BYTES
    chunks = []
    total = 0
    try:
        while True:
            chunk = await file.read(_READ_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status_code=400,
                    detail=f"File size exceeds the {settings.MAX_FILE_SIZE_MB} MB limit.",
                )
            chunks.append(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to read uploaded file: {e}")
        raise HTTPException(status_code=400, detail="Could not read uploaded file.")

    file_bytes = b"".join(chunks)
    del chunks

    # ── Pre-pipeline validation ───────────────────────────────────────────────
    # Extension, non-empty, size, and magic-bytes are all checked here so bad
    # uploads are rejected cheaply (400) before any parsing or LLM work.
    try:
        validate_upload(file_bytes, filename)
    except ValueError as e:
        logger.warning(f"Upload rejected for {filename}: {e}")
        del file_bytes
        raise HTTPException(status_code=400, detail=str(e))

    # ── Run pipeline ──────────────────────────────────────────────────────────
    try:
        result = run_pipeline(file_bytes, filename)
    except GeminiQuotaExhaustedError as e:
        # Free-tier quota / rate limit used up — not an internal fault. Surface a
        # clear 429 with an actionable message so a reviewer knows exactly what
        # happened (rather than seeing a generic 500).
        logger.warning(f"Gemini quota exhausted while analyzing {filename}")
        raise HTTPException(status_code=429, detail=str(e))
    except ValueError as e:
        # User-facing errors (bad file, unreadable content)
        logger.warning(f"Pipeline validation error: {e}")
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # Internal errors — log details but don't expose to client
        logger.error(f"Pipeline error for {filename}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An error occurred during document analysis. Please try again."
        )
    finally:
        # Explicitly clear file bytes from memory after processing
        del file_bytes

    # Encode the .docx report inline so the client can download it without the
    # server persisting anything (in-memory, stateless — matches the security model).
    report_bytes = result.get("report_bytes")
    report_docx_base64 = (
        base64.b64encode(report_bytes).decode("ascii") if report_bytes else None
    )

    return JSONResponse(content={
        "status": "success",
        "filename": filename,
        "document_type": result.get("metadata", {}).get("document_type"),
        "policy_data": result.get("policy_data"),
        "coverage_map": result.get("coverage_map"),
        "financial_verdict": result.get("financial_verdict"),
        "risk_flags": result.get("risk_flags"),
        "report_intros": result.get("report_intros"),
        "report_docx_base64": report_docx_base64,
        "metadata": result.get("metadata"),
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=(settings.APP_ENV == "development"),
        log_level=settings.LOG_LEVEL.lower(),
    )
