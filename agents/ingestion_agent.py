"""
InsureIQ — Ingestion Agent (Agent 1)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Role: First agent in the pipeline. Receives raw file bytes from the MCP file server,
extracts text, detects the insurance document type, and splits content into labeled
sections for downstream agents.

Output: IngestionResult JSON — consumed by Agent 2 (Policy Extractor)

Kaggle concepts demonstrated:
  - ADK Agent with defined role
  - MCP integration (receives file from MCP file server)
  - Security: file processed in memory only, never written to disk
"""

import logging
from typing import Optional

import google.generativeai as genai
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from config.settings import settings
from config.agent_prompts import INGESTION_SYSTEM_PROMPT, INGESTION_TYPE_DETECTION_PROMPT
from agents.gemini_utils import call_gemini_with_retry, parse_gemini_json_response
from tools.document_parser import (
    extract_text_from_pdf,
    extract_text_from_docx,
    detect_file_extension,
    validate_file_size,
)

logger = logging.getLogger(__name__)

# Keyword fast-path thresholds. The classifier only skips the Gemini call when a
# type has at least MIN_KEYWORD_SCORE matches AND leads the runner-up by at least
# KEYWORD_CONFIDENCE_MARGIN — otherwise it's too close to call and we defer to
# Gemini. (A pure count >= 2 with no margin mislabels hybrid docs, e.g. a
# health-cum-endowment policy that scores on both health and life keywords.)
MIN_KEYWORD_SCORE = 2
KEYWORD_CONFIDENCE_MARGIN = 2

# How much text the keyword scan reads. Kept to the opening pages (declarations
# + schedule) where type vocabulary is densest — but wide enough that keywords
# living in a DOCX's tables (python-docx appends all tables *after* the body
# paragraphs) still land inside the window. 3000 was too tight for table-heavy
# schedules; 6000 covers them without pulling in unrelated late-document noise.
KEYWORD_SAMPLE_CHARS = 6000


def _detect_document_type_by_keywords(text: str) -> str:
    """
    Fast keyword-based document type detection.
    Run this first — if confident, skip the Gemini API call to save latency.

    Args:
        text: Extracted document text (first KEYWORD_SAMPLE_CHARS chars used)

    Returns:
        Document type: "health" | "life" | "car" | "home" | "unknown"
    """
    sample = text[:KEYWORD_SAMPLE_CHARS].lower()
    scores = {}

    for doc_type, keywords in settings.DOC_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in sample)
        scores[doc_type] = score
        logger.debug(f"Type detection score — {doc_type}: {score}")

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_type, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0

    # Only trust the keyword fast-path when there's a CLEAR winner: enough raw
    # matches AND a decisive lead over the runner-up. The margin guard matters
    # for hybrid documents — e.g. a "health cum savings endowment" policy scores
    # on both health and life keywords, and a bare 3-vs-2 edge is not enough to
    # confidently pick one. When it's close, we return "unknown" and let the
    # Gemini classifier (which reads meaning, not keyword counts) decide.
    if best_score >= MIN_KEYWORD_SCORE and (best_score - second_score) >= KEYWORD_CONFIDENCE_MARGIN:
        logger.info(
            f"Document type detected by keywords: {best_type} "
            f"(score: {best_score}, margin: {best_score - second_score})"
        )
        return best_type

    logger.info(
        f"Keyword detection inconclusive (best: {best_type}={best_score}, "
        f"runner-up={second_score}). Will use Gemini."
    )
    return "unknown"


def _detect_document_type_with_gemini(text: str, model) -> str:
    """
    Fallback: use Gemini to classify document type when keywords are inconclusive.

    Args:
        text: Extracted document text
        model: Configured Gemini model instance

    Returns:
        Document type string
    """
    prompt = INGESTION_TYPE_DETECTION_PROMPT.format(text_sample=text[:2000])

    try:
        response = call_gemini_with_retry(model, prompt, "")
        doc_type = response.strip().lower()

        if doc_type in {"health", "life", "car", "home"}:
            logger.info(f"Gemini classified document as: {doc_type}")
            return doc_type

        logger.warning(f"Gemini returned unexpected type: '{doc_type}'. Defaulting to 'unknown'.")
        return "unknown"

    except Exception as e:
        logger.error(f"Gemini type detection failed: {e}. Defaulting to 'unknown'.")
        return "unknown"


def run_ingestion_agent(file_bytes: bytes, filename: str) -> dict:
    """
    Main entry point for the Ingestion Agent.

    Steps:
    1. Validate file (type + size)
    2. Extract text (pdfplumber → Gemini vision fallback for scanned PDFs)
    3. Detect document type (keywords → Gemini fallback)
    4. Split into labeled sections using Gemini
    5. Return structured IngestionResult

    Args:
        file_bytes: Raw file content (processed in memory only — never written to disk)
        filename: Original filename (used only for extension detection)

    Returns:
        IngestionResult dict with sections and metadata

    Raises:
        ValueError: On invalid file type, size, or unreadable content
        RuntimeError: On Gemini API failure
    """
    logger.info(f"Ingestion Agent starting — file: {filename}, size: {len(file_bytes)} bytes")

    # ── Step 1: Validate input ────────────────────────────────────────────────
    file_ext = detect_file_extension(filename)
    validate_file_size(file_bytes, settings.MAX_FILE_SIZE_BYTES)

    # ── Step 2: Extract text ──────────────────────────────────────────────────
    if file_ext == "pdf":
        raw_text, extraction_method = extract_text_from_pdf(file_bytes)
    else:  # docx
        raw_text, extraction_method = extract_text_from_docx(file_bytes)

    if len(raw_text.strip()) < 50:
        raise ValueError(
            "Could not extract readable text from the document. "
            "Please ensure the file is not password-protected or completely blank."
        )

    logger.info(f"Text extraction complete: {len(raw_text)} chars via {extraction_method}")

    # ── Step 3: Configure Gemini ──────────────────────────────────────────────
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        system_instruction=INGESTION_SYSTEM_PROMPT,
    )

    # ── Step 4: Detect document type ──────────────────────────────────────────
    doc_type = _detect_document_type_by_keywords(raw_text)
    if doc_type == "unknown":
        doc_type = _detect_document_type_with_gemini(raw_text, model)

    # ── Step 5: Split into labeled sections ───────────────────────────────────
    # Pass full text to Gemini — 1M context window handles entire insurance docs
    section_prompt = (
        f"Split this {doc_type} insurance document into labeled sections as specified.\n\n"
        f"DOCUMENT TEXT:\n{raw_text}"
    )

    logger.info("Calling Gemini for section splitting...")
    raw_response = call_gemini_with_retry(model, section_prompt, INGESTION_SYSTEM_PROMPT)
    section_data = parse_gemini_json_response(raw_response)

    # ── Step 6: Build and return IngestionResult ──────────────────────────────
    result = {
        "status": "success",
        "filename": filename,
        "file_extension": file_ext,
        "extraction_method": extraction_method,
        "document_type": doc_type,
        "raw_text_length": len(raw_text),
        "sections": section_data.get("sections", {}),
        # Pass raw_text for agents that need it (e.g., Risk Flag Agent does full-doc scan)
        "raw_text": raw_text,
    }

    logger.info(
        f"Ingestion Agent complete — type: {doc_type}, "
        f"sections found: {[k for k, v in result['sections'].items() if v]}"
    )

    return result


# ─── ADK Agent Definition ────────────────────────────────────────────────────
# Wraps run_ingestion_agent as an ADK LlmAgent with a FunctionTool
# so it participates properly in the multi-agent ADK pipeline.

def create_ingestion_agent() -> LlmAgent:
    """
    Create and return the ADK LlmAgent for ingestion.
    Called by pipeline.py during pipeline construction.

    Returns:
        Configured ADK LlmAgent instance
    """
    ingestion_tool = FunctionTool(
        func=run_ingestion_agent,
        name="ingest_document",
        description=(
            "Ingests an insurance document (PDF or DOCX), extracts text, "
            "detects document type (health/life/car/home), and splits content "
            "into labeled sections for downstream analysis."
        ),
    )

    agent = LlmAgent(
        name="IngestionAgent",
        model=settings.GEMINI_MODEL,
        description="Agent 1: Parses insurance documents and produces labeled section data.",
        tools=[ingestion_tool],
    )

    logger.info("IngestionAgent created")
    return agent
