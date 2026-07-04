"""
InsureIQ — Policy Extractor Agent (Agent 2)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Role: Second agent in the pipeline. Receives the labeled sections produced by the
Ingestion Agent and extracts structured policy facts — dates, premiums, maturity,
nominee, lapse conditions — into a strict JSON schema for downstream agents.

Input:  IngestionResult dict (from Agent 1)
Output: PolicyData dict — consumed by Agent 4 (Financial Evaluator) and Agent 6 (Report Composer)

Kaggle concepts demonstrated:
  - ADK Agent with a defined role in a sequential multi-agent chain
  - Structured extraction with a strict JSON schema + low-temperature decoding
"""

import logging

import google.generativeai as genai
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from config.settings import settings
from config.agent_prompts import POLICY_EXTRACTOR_SYSTEM_PROMPT
from agents.gemini_utils import call_gemini_with_retry, parse_gemini_json_response

logger = logging.getLogger(__name__)

# Sections most likely to contain hard policy facts. Ordered by relevance so the
# prompt leads with the highest-signal content. The Policy Extractor does NOT need
# the coverage/exclusions prose — that is Agent 3's job.
RELEVANT_SECTIONS = [
    "premium_schedule",
    "maturity_clause",
    "terms_and_conditions",
    "definitions",
    "coverage_terms",
]

# Fields we promise downstream agents. Used to normalise partial Gemini output so
# consumers can rely on every key existing (missing → null / empty list).
EXPECTED_STRING_FIELDS = [
    "policy_number",
    "insurer_name",
    "policyholder_name",
    "policy_start_date",
    "policy_end_date",
    "policy_term_years",
    "premium_paying_term_years",
    "sum_assured",
    "premium_amount",
    "premium_frequency",
    "grace_period_days",
    "maturity_date",
    "maturity_benefit",
    "free_look_period_days",
    "nominee_name",
    "loan_against_policy",
]
EXPECTED_LIST_FIELDS = ["premium_due_dates", "lapse_conditions"]

# Identity fields (policy number, insurer, policyholder, nominee) live in the
# policy schedule / declarations table at the top of the document — which the
# ingestion splitter has no section bucket for. Always prepend the document head
# so these fields are extracted reliably rather than by chance.
HEADER_CHARS = 2500


def _build_extraction_prompt(ingestion_result: dict) -> str:
    """
    Assemble the extraction prompt from the document header + ingestion sections.

    Always includes the document head (the policy schedule / declarations block,
    the only reliable source for policy number, insurer, policyholder and nominee).
    Falls back to the full raw text if section splitting produced nothing useful —
    a poorly-structured document should still get a best-effort extraction.

    Args:
        ingestion_result: Output dict from run_ingestion_agent

    Returns:
        Prompt string to send to Gemini
    """
    sections = ingestion_result.get("sections", {}) or {}
    doc_type = ingestion_result.get("document_type", "unknown")
    raw_text = (ingestion_result.get("raw_text") or "").strip()

    parts = []

    # The schedule/declarations table (policy no., insurer, policyholder, nominee)
    # is not a labeled section — grab it straight from the top of the raw text.
    if raw_text:
        parts.append(f"### DOCUMENT HEADER (policy schedule / declarations)\n{raw_text[:HEADER_CHARS]}")

    for key in RELEVANT_SECTIONS:
        content = (sections.get(key) or "").strip()
        if content:
            parts.append(f"### {key.upper()}\n{content}")

    # Fallback: if the ingestion agent found no usable sections and no header text,
    # hand over the raw text so the extractor still has something to work with.
    if not parts:
        logger.warning("Policy Extractor: no labeled sections found — falling back to raw text")
        body = raw_text if raw_text else "(no document content available)"
    else:
        body = "\n\n".join(parts)

    return (
        f"Extract structured policy data from this {doc_type} insurance document.\n\n"
        f"{body}"
    )


def _normalize_policy_data(data: dict) -> dict:
    """
    Guarantee every promised field exists so downstream agents never KeyError.

    Args:
        data: Raw parsed dict from Gemini

    Returns:
        Dict with all expected keys present (missing strings → None, lists → [])
    """
    normalized = {}
    for field in EXPECTED_STRING_FIELDS:
        normalized[field] = data.get(field)
    for field in EXPECTED_LIST_FIELDS:
        value = data.get(field)
        normalized[field] = value if isinstance(value, list) else ([] if value is None else [value])
    return normalized


def run_policy_extractor_agent(ingestion_result: dict) -> dict:
    """
    Main entry point for the Policy Extractor Agent.

    Steps:
    1. Assemble a prompt from the ingestion sections (fallback: raw text)
    2. Call Gemini with the strict policy-extraction schema
    3. Parse + normalise the JSON so every promised field is present
    4. Return structured PolicyData

    Args:
        ingestion_result: Output dict from run_ingestion_agent (Agent 1)

    Returns:
        PolicyData dict with status + all schema fields

    Raises:
        ValueError: If Gemini returns unparseable JSON
        RuntimeError: On Gemini API failure after retries
    """
    doc_type = ingestion_result.get("document_type", "unknown")
    logger.info(f"Policy Extractor Agent starting — document type: {doc_type}")

    # ── Step 1: Build the prompt ──────────────────────────────────────────────
    extraction_prompt = _build_extraction_prompt(ingestion_result)

    # ── Step 2: Configure Gemini ──────────────────────────────────────────────
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        system_instruction=POLICY_EXTRACTOR_SYSTEM_PROMPT,
    )

    # ── Step 3: Extract + parse ───────────────────────────────────────────────
    logger.info("Calling Gemini for policy field extraction...")
    raw_response = call_gemini_with_retry(model, extraction_prompt, POLICY_EXTRACTOR_SYSTEM_PROMPT)
    parsed = parse_gemini_json_response(raw_response)
    policy_data = _normalize_policy_data(parsed)

    # ── Step 4: Build result ──────────────────────────────────────────────────
    result = {"status": "success", **policy_data}

    populated = [k for k in EXPECTED_STRING_FIELDS if result.get(k) not in (None, "")]
    logger.info(
        f"Policy Extractor Agent complete — {len(populated)}/{len(EXPECTED_STRING_FIELDS)} "
        f"fields populated: {populated}"
    )

    return result


# ─── ADK Agent Definition ────────────────────────────────────────────────────

def create_policy_extractor_agent() -> LlmAgent:
    """
    Create and return the ADK LlmAgent for policy extraction.
    Called by pipeline.py during pipeline construction.

    Returns:
        Configured ADK LlmAgent instance
    """
    extractor_tool = FunctionTool(
        func=run_policy_extractor_agent,
        name="extract_policy_data",
        description=(
            "Extracts structured policy facts (policy number, dates, premiums, "
            "sum assured, maturity, nominee, lapse conditions) from ingested "
            "insurance document sections into a strict JSON schema."
        ),
    )

    agent = LlmAgent(
        name="PolicyExtractorAgent",
        model=settings.GEMINI_MODEL,
        description="Agent 2: Extracts structured policy data from labeled document sections.",
        tools=[extractor_tool],
    )

    logger.info("PolicyExtractorAgent created")
    return agent
