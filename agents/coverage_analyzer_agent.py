"""
InsureIQ — Coverage Analyzer Agent (Agent 3)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Role: Third agent in the pipeline. Reads the coverage and exclusions sections from
the Ingestion Agent and produces a structured coverage map — what is covered, what
is excluded, waiting periods, and sub-limits — plus a plain-English summary.

Input:  IngestionResult dict (from Agent 1)
Output: CoverageMap dict — consumed by Agent 6 (Report Composer)

Kaggle concepts demonstrated:
  - ADK Agent with a defined role in a sequential multi-agent chain
  - Structured analysis with a strict JSON schema + low-temperature decoding
"""

import logging

import google.generativeai as genai
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from config.settings import settings
from config.agent_prompts import COVERAGE_ANALYZER_SYSTEM_PROMPT
from agents.gemini_utils import call_gemini_with_retry, parse_gemini_json_response

logger = logging.getLogger(__name__)

# Coverage analysis lives almost entirely in these two sections. Definitions is
# included because exclusions frequently reference defined terms ("as defined in...").
RELEVANT_SECTIONS = ["coverage_terms", "exclusions", "definitions"]

# List fields we promise downstream. Normalised so consumers can iterate safely.
EXPECTED_LIST_FIELDS = ["covered_events", "excluded_events", "waiting_periods", "sub_limits"]


def _build_coverage_prompt(ingestion_result: dict) -> str:
    """
    Assemble the coverage-analysis prompt from the ingestion sections.

    Falls back to the full raw text when section splitting yielded nothing useful —
    exclusions buried outside a labeled section should still be caught.

    Args:
        ingestion_result: Output dict from run_ingestion_agent

    Returns:
        Prompt string to send to Gemini
    """
    sections = ingestion_result.get("sections", {}) or {}
    doc_type = ingestion_result.get("document_type", "unknown")

    parts = []
    for key in RELEVANT_SECTIONS:
        content = (sections.get(key) or "").strip()
        if content:
            parts.append(f"### {key.upper()}\n{content}")

    if not parts:
        raw_text = (ingestion_result.get("raw_text") or "").strip()
        logger.warning("Coverage Analyzer: no labeled sections found — falling back to raw text")
        body = raw_text if raw_text else "(no document content available)"
    else:
        body = "\n\n".join(parts)

    return (
        f"Analyze the coverage and exclusions of this {doc_type} insurance policy.\n\n"
        f"{body}"
    )


def _normalize_coverage_map(data: dict) -> dict:
    """
    Guarantee every promised field exists so downstream agents never KeyError.

    Args:
        data: Raw parsed dict from Gemini

    Returns:
        Dict with all list fields present as lists and a coverage_summary string
    """
    normalized = {}
    for field in EXPECTED_LIST_FIELDS:
        value = data.get(field)
        normalized[field] = value if isinstance(value, list) else ([] if value is None else [value])
    normalized["coverage_summary"] = data.get("coverage_summary") or ""
    return normalized


def run_coverage_analyzer_agent(ingestion_result: dict) -> dict:
    """
    Main entry point for the Coverage Analyzer Agent.

    Steps:
    1. Assemble a prompt from the coverage/exclusions sections (fallback: raw text)
    2. Call Gemini with the strict coverage-map schema
    3. Parse + normalise the JSON so every promised field is present
    4. Return the structured CoverageMap

    Args:
        ingestion_result: Output dict from run_ingestion_agent (Agent 1)

    Returns:
        CoverageMap dict with status + all schema fields

    Raises:
        ValueError: If Gemini returns unparseable JSON
        RuntimeError: On Gemini API failure after retries
    """
    doc_type = ingestion_result.get("document_type", "unknown")
    logger.info(f"Coverage Analyzer Agent starting — document type: {doc_type}")

    # ── Step 1: Build the prompt ──────────────────────────────────────────────
    coverage_prompt = _build_coverage_prompt(ingestion_result)

    # ── Step 2: Configure Gemini ──────────────────────────────────────────────
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        system_instruction=COVERAGE_ANALYZER_SYSTEM_PROMPT,
    )

    # ── Step 3: Analyze + parse ───────────────────────────────────────────────
    logger.info("Calling Gemini for coverage analysis...")
    raw_response = call_gemini_with_retry(model, coverage_prompt, COVERAGE_ANALYZER_SYSTEM_PROMPT)
    parsed = parse_gemini_json_response(raw_response)
    coverage_map = _normalize_coverage_map(parsed)

    # ── Step 4: Build result ──────────────────────────────────────────────────
    result = {"status": "success", **coverage_map}

    logger.info(
        f"Coverage Analyzer Agent complete — "
        f"{len(result['covered_events'])} covered, "
        f"{len(result['excluded_events'])} excluded, "
        f"{len(result['waiting_periods'])} waiting periods, "
        f"{len(result['sub_limits'])} sub-limits"
    )

    return result


# ─── ADK Agent Definition ────────────────────────────────────────────────────

def create_coverage_analyzer_agent() -> LlmAgent:
    """
    Create and return the ADK LlmAgent for coverage analysis.
    Called by pipeline.py during pipeline construction.

    Returns:
        Configured ADK LlmAgent instance
    """
    coverage_tool = FunctionTool(
        func=run_coverage_analyzer_agent,
        name="analyze_coverage",
        description=(
            "Analyzes the coverage and exclusions sections of an insurance policy "
            "and produces a structured coverage map: covered events, exclusions, "
            "waiting periods, sub-limits, and a plain-English summary."
        ),
    )

    agent = LlmAgent(
        name="CoverageAnalyzerAgent",
        model=settings.GEMINI_MODEL,
        description="Agent 3: Produces a structured coverage map from policy sections.",
        tools=[coverage_tool],
    )

    logger.info("CoverageAnalyzerAgent created")
    return agent
