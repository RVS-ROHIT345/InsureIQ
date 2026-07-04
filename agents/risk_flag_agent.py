"""
InsureIQ — Risk Flag Agent (Agent 5)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Role: Fifth agent in the pipeline. Scans the whole document for the traps most
policyholders miss — auto-renewal, surrender penalties, claim-rejection triggers,
free-look expiry, unreachable maturity ages — and classifies each by severity.

Design: Gemini surfaces the clauses; the severity tallies and overall risk level
are then recomputed deterministically here, so the summary counts can never
disagree with the flags list (a common failure when you trust the LLM's own math).

Input:  IngestionResult dict (from Agent 1) — needs the full document, not just
        one section, because traps hide anywhere.
Output: RiskFlags dict — consumed by Agent 6 (Report Composer)

Kaggle concepts demonstrated:
  - ADK Agent with a defined role in a sequential multi-agent chain
  - Structured classification with a strict JSON schema + low-temperature decoding
"""

import logging

import google.generativeai as genai
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from config.settings import settings
from config.agent_prompts import RISK_FLAG_SYSTEM_PROMPT
from agents.gemini_utils import call_gemini_with_retry, parse_gemini_json_response

logger = logging.getLogger(__name__)

# Fine print hides everywhere, so we feed the risk hunter every section we have.
# Exclusions and T&C lead because that's where the worst traps usually live.
RELEVANT_SECTIONS = [
    "exclusions",
    "terms_and_conditions",
    "premium_schedule",
    "maturity_clause",
    "coverage_terms",
    "definitions",
]

VALID_SEVERITIES = {"HIGH", "MEDIUM", "LOW"}
# Sort order for presenting flags worst-first.
_SEVERITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

# Cap raw-text fallback so a huge scanned doc can't blow up the prompt when the
# ingestion agent produced no labeled sections. The full context window is large,
# but there's no value in dumping 100 pages of boilerplate at the risk hunter.
RAW_TEXT_CAP = 30_000


def _build_risk_prompt(ingestion_result: dict) -> str:
    """
    Assemble the risk-scan prompt from all available document sections.

    Falls back to (capped) raw text when the ingestion agent produced no labeled
    sections — traps outside any recognised section must still be caught.

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
        logger.warning("Risk Flag: no labeled sections found — falling back to raw text")
        body = raw_text[:RAW_TEXT_CAP] if raw_text else "(no document content available)"
    else:
        body = "\n\n".join(parts)

    return (
        f"Scan this {doc_type} insurance policy for hidden traps and unfavorable "
        f"clauses. Classify each by severity.\n\n{body}"
    )


def _normalize_risk_flags(data: dict) -> dict:
    """
    Clean the flags list and recompute all summary counts from it.

    We deliberately ignore Gemini's own total_high/medium/low and overall_risk_level
    — they're recomputed from the actual flags so the numbers always reconcile.

    Args:
        data: Raw parsed dict from Gemini

    Returns:
        Dict with a sorted `flags` list, severity tallies, and overall_risk_level
    """
    raw_flags = data.get("flags")
    if isinstance(raw_flags, dict):
        raw_flags = [raw_flags]
    elif not isinstance(raw_flags, list):
        raw_flags = []

    clean_flags = []
    for flag in raw_flags:
        if not isinstance(flag, dict):
            continue
        severity = str(flag.get("severity", "")).strip().upper()
        if severity not in VALID_SEVERITIES:
            severity = "LOW"  # unclassifiable → treat conservatively, don't drop it
        clean_flags.append({
            "severity": severity,
            "category": flag.get("category") or "Uncategorized",
            "description": flag.get("description") or "",
            "implication": flag.get("implication") or "",
            "page_reference": flag.get("page_reference") or "",
        })

    clean_flags.sort(key=lambda f: _SEVERITY_RANK[f["severity"]])

    total_high = sum(1 for f in clean_flags if f["severity"] == "HIGH")
    total_medium = sum(1 for f in clean_flags if f["severity"] == "MEDIUM")
    total_low = sum(1 for f in clean_flags if f["severity"] == "LOW")

    if total_high:
        overall = "HIGH"
    elif total_medium:
        overall = "MEDIUM"
    elif total_low:
        overall = "LOW"
    else:
        overall = "NONE"

    return {
        "flags": clean_flags,
        "total_high": total_high,
        "total_medium": total_medium,
        "total_low": total_low,
        "overall_risk_level": overall,
    }


def run_risk_flag_agent(ingestion_result: dict) -> dict:
    """
    Main entry point for the Risk Flag Agent.

    Steps:
    1. Assemble a whole-document prompt (fallback: capped raw text)
    2. Call Gemini to surface hidden clauses with a strict JSON schema
    3. Parse, clean, sort worst-first, and recompute severity tallies deterministically
    4. Return the structured RiskFlags

    Args:
        ingestion_result: Output dict from run_ingestion_agent (Agent 1)

    Returns:
        RiskFlags dict with status + flags + tallies + overall_risk_level

    Raises:
        ValueError: If Gemini returns unparseable JSON
        RuntimeError: On Gemini API failure after retries
    """
    doc_type = ingestion_result.get("document_type", "unknown")
    logger.info(f"Risk Flag Agent starting — document type: {doc_type}")

    # ── Step 1: Build the prompt ──────────────────────────────────────────────
    risk_prompt = _build_risk_prompt(ingestion_result)

    # ── Step 2: Configure Gemini ──────────────────────────────────────────────
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        system_instruction=RISK_FLAG_SYSTEM_PROMPT,
    )

    # ── Step 3: Scan + parse + recompute counts ───────────────────────────────
    logger.info("Calling Gemini for risk/fine-print scan...")
    raw_response = call_gemini_with_retry(model, risk_prompt, RISK_FLAG_SYSTEM_PROMPT)
    parsed = parse_gemini_json_response(raw_response)
    risk_flags = _normalize_risk_flags(parsed)

    # ── Step 4: Build result ──────────────────────────────────────────────────
    result = {"status": "success", **risk_flags}

    logger.info(
        f"Risk Flag Agent complete — overall: {result['overall_risk_level']} "
        f"({result['total_high']} high, {result['total_medium']} medium, {result['total_low']} low)"
    )
    return result


# ─── ADK Agent Definition ────────────────────────────────────────────────────

def create_risk_flag_agent() -> LlmAgent:
    """
    Create and return the ADK LlmAgent for risk flagging.
    Called by pipeline.py during pipeline construction.

    Returns:
        Configured ADK LlmAgent instance
    """
    risk_tool = FunctionTool(
        func=run_risk_flag_agent,
        name="flag_risks",
        description=(
            "Scans an insurance policy for hidden traps and unfavorable clauses "
            "(auto-renewal, surrender penalties, claim-rejection triggers, free-look "
            "expiry, unreachable maturity ages) and classifies each by severity."
        ),
    )

    agent = LlmAgent(
        name="RiskFlagAgent",
        model=settings.GEMINI_MODEL,
        description="Agent 5: Surfaces and ranks the fine-print risks in a policy.",
        tools=[risk_tool],
    )

    logger.info("RiskFlagAgent created")
    return agent
