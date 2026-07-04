"""
InsureIQ — Report Composer Agent (Agent 6)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Role: Final agent in the pipeline. Takes the structured outputs of Agents 2–5 and
does two things:
  1. Asks Gemini to write short, plain-English section introductions + an overall
     recommendation, given a compact summary of everything the earlier agents found.
  2. Hands those intros plus all the structured data to tools/report_generator.py,
     which assembles the formatted .docx the customer actually downloads.

Design: Gemini writes ONLY narrative prose (titles, intros, recommendation). Every
figure, flag, and fact in the report comes from the upstream agents — Agent 6 never
invents data, mirroring the numbers-vs-prose split used by Agent 4.

Input:  PolicyData, CoverageMap, FinancialVerdict, RiskFlags (Agents 2–5)
Output: ReportResult dict — report_intros + report_bytes (final .docx)

Kaggle concepts demonstrated:
  - ADK Agent with a defined role in a sequential multi-agent chain
  - Agent Skills — report_generator.py registered as an ADK FunctionTool
"""

import logging

import google.generativeai as genai
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from config.settings import settings
from config.agent_prompts import REPORT_COMPOSER_SYSTEM_PROMPT
from agents.gemini_utils import call_gemini_with_retry, parse_gemini_json_response
from tools.report_generator import generate_report

logger = logging.getLogger(__name__)

# Intro keys we promise the report generator. Every one is guaranteed present after
# normalization so the .docx builder never has to guard for missing narrative.
_EXPECTED_INTRO_FIELDS = [
    "report_title",
    "executive_summary",
    "dates_section_intro",
    "financial_section_intro",
    "risk_section_intro",
    "recommendation",
]


def _summarize_for_prompt(
    policy_data: dict,
    coverage_map: dict,
    financial_verdict: dict,
    risk_flags: dict,
    document_type: str,
) -> str:
    """
    Build a compact digest of the upstream findings for Gemini to write around.

    We deliberately pass a summary, not the raw dumps — Agent 6 writes prose, so it
    needs the headline facts (verdict, risk level, top flags), not every field.
    """
    insurer = policy_data.get("insurer_name") or "Unknown insurer"
    premium = policy_data.get("premium_amount") or "not specified"
    term = policy_data.get("policy_term_years") or "not specified"

    coverage_summary = (coverage_map.get("coverage_summary") or "").strip() or "not summarized"
    n_covered = len(coverage_map.get("covered_events", []))
    n_excluded = len(coverage_map.get("excluded_events", []))

    verdict = financial_verdict.get("verdict") or "UNKNOWN"
    fin_plain = (financial_verdict.get("verdict_plain_english") or "").strip()
    cagr = financial_verdict.get("effective_annual_return_pct")

    overall_risk = risk_flags.get("overall_risk_level") or "NONE"
    top_flags = [
        f"- [{f.get('severity')}] {f.get('category')}: {f.get('implication') or f.get('description') or ''}"
        for f in risk_flags.get("flags", [])[:5]
        if isinstance(f, dict)
    ]
    flags_block = "\n".join(top_flags) if top_flags else "- (no notable flags)"

    return (
        f"Document type: {document_type} insurance\n"
        f"Insurer: {insurer}\n"
        f"Premium: {premium} | Term: {term} years\n\n"
        f"COVERAGE ({n_covered} covered events, {n_excluded} exclusions):\n{coverage_summary}\n\n"
        f"FINANCIAL VERDICT: {verdict}"
        + (f" (effective annual return {cagr}%)" if cagr is not None else "")
        + (f"\n{fin_plain}" if fin_plain else "")
        + f"\n\nRISK LEVEL: {overall_risk} "
        f"({risk_flags.get('total_high', 0)} high / {risk_flags.get('total_medium', 0)} medium / "
        f"{risk_flags.get('total_low', 0)} low)\n"
        f"Top flags:\n{flags_block}\n"
    )


def _build_composer_prompt(summary: str, document_type: str) -> str:
    """Assemble the narrative-writing prompt from the findings digest."""
    return (
        f"Write the section introductions and recommendation for the analysis report "
        f"of this {document_type} insurance policy, based on the findings below. Be "
        f"honest and direct — if the policy is a poor deal or hides serious traps, say "
        f"so plainly.\n\n{summary}"
    )


def _normalize_report_intros(data: dict, policy_data: dict, document_type: str) -> dict:
    """
    Guarantee every intro key exists so the .docx generator never KeyErrors.

    Missing narrative falls back to sensible, honest defaults rather than blank text.
    """
    insurer = policy_data.get("insurer_name") or "Unknown Insurer"
    default_title = f"InsureIQ Analysis: {document_type.title()} Policy — {insurer}"

    normalized = {field: (data.get(field) or "").strip() for field in _EXPECTED_INTRO_FIELDS}
    if not normalized["report_title"]:
        normalized["report_title"] = default_title
    return normalized


def run_report_composer_agent(
    policy_data: dict,
    coverage_map: dict,
    financial_verdict: dict,
    risk_flags: dict,
    document_type: str = "unknown",
) -> dict:
    """
    Main entry point for the Report Composer Agent.

    Steps:
    1. Digest the upstream findings into a compact summary
    2. Ask Gemini to write section intros + an overall recommendation
    3. Normalise the intros so every promised key is present
    4. Assemble the final .docx via report_generator (pure document assembly)

    Args:
        policy_data: Output from Policy Extractor Agent (Agent 2)
        coverage_map: Output from Coverage Analyzer Agent (Agent 3)
        financial_verdict: Output from Financial Evaluator Agent (Agent 4)
        risk_flags: Output from Risk Flag Agent (Agent 5)
        document_type: Insurance type from the Ingestion Agent (Agent 1)

    Returns:
        ReportResult dict with status + report_intros + report_bytes (.docx)

    Raises:
        ValueError: If Gemini returns unparseable JSON
        RuntimeError: On Gemini API failure after retries
    """
    logger.info(f"Report Composer Agent starting — document type: {document_type}")

    # ── Step 1: Digest upstream findings ──────────────────────────────────────
    summary = _summarize_for_prompt(
        policy_data, coverage_map, financial_verdict, risk_flags, document_type
    )

    # ── Step 2: Configure Gemini + write the narrative ────────────────────────
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        system_instruction=REPORT_COMPOSER_SYSTEM_PROMPT,
    )

    logger.info("Calling Gemini to write report section intros...")
    prompt = _build_composer_prompt(summary, document_type)
    raw_response = call_gemini_with_retry(model, prompt, REPORT_COMPOSER_SYSTEM_PROMPT)
    parsed = parse_gemini_json_response(raw_response)

    # ── Step 3: Normalise intros ──────────────────────────────────────────────
    report_intros = _normalize_report_intros(parsed, policy_data, document_type)

    # ── Step 4: Assemble the .docx (no LLM — pure layout) ─────────────────────
    report_bytes = generate_report(
        policy_data=policy_data,
        coverage_map=coverage_map,
        financial_verdict=financial_verdict,
        risk_flags=risk_flags,
        report_intros=report_intros,
    )

    logger.info(
        f"Report Composer Agent complete — title: '{report_intros['report_title']}', "
        f"{len(report_bytes)} bytes"
    )
    return {
        "status": "success",
        "report_intros": report_intros,
        "report_bytes": report_bytes,
    }


# ─── ADK Agent Definition ────────────────────────────────────────────────────

def create_report_composer_agent() -> LlmAgent:
    """
    Create and return the ADK LlmAgent for report composition.
    Called by pipeline.py during pipeline construction.

    Returns:
        Configured ADK LlmAgent instance
    """
    report_tool = FunctionTool(
        func=run_report_composer_agent,
        name="compose_report",
        description=(
            "Writes plain-English section introductions and an overall recommendation "
            "for an insurance analysis report, then assembles the final formatted .docx "
            "from all upstream agent outputs."
        ),
    )

    agent = LlmAgent(
        name="ReportComposerAgent",
        model=settings.GEMINI_MODEL,
        description="Agent 6: Composes the final plain-English .docx analysis report.",
        tools=[report_tool],
    )

    logger.info("ReportComposerAgent created")
    return agent
