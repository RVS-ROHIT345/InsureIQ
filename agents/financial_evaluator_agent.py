"""
InsureIQ — Financial Evaluator Agent (Agent 4)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Role: Fourth agent in the pipeline. Takes the structured facts from the Policy
Extractor (premiums, term, maturity benefit) and answers the question every
customer actually cares about: "is this policy worth the money?"

Design: numbers are computed deterministically by tools/financial_calculator.py
(an ADK FunctionTool). Gemini is used ONLY to translate those numbers into a
plain-English verdict — it never invents figures. This split keeps the money
maths trustworthy while still producing human-readable output.

Input:  PolicyData dict (from Agent 2)
Output: FinancialVerdict dict — consumed by Agent 6 (Report Composer)

Kaggle concepts demonstrated:
  - Agent Skills — financial_calculator.py registered as an ADK FunctionTool
  - ADK Agent with a defined role in a sequential multi-agent chain
"""

import logging
from datetime import date

import google.generativeai as genai
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from config.settings import settings
from config.agent_prompts import FINANCIAL_EVALUATOR_SYSTEM_PROMPT
from agents.gemini_utils import call_gemini_with_retry, parse_gemini_json_response
from tools.financial_calculator import (
    parse_currency_to_float,
    parse_term_years,
    detect_currency_symbol,
    calculate_total_premium,
    build_financial_verdict,
)

logger = logging.getLogger(__name__)

# Every FinancialVerdict we return carries these keys so Agent 6 never KeyErrors,
# regardless of which branch (full analysis / no maturity / insufficient data) ran.
_METRIC_FIELDS = [
    "total_premium_paid",
    "maturity_benefit",
    "net_gain_loss",
    "effective_annual_return_pct",
    "fd_benchmark_return",
    "index_fund_benchmark_return",
    "fd_benchmark_pct",
    "index_fund_benchmark_pct",
    "verdict",
]


def _derive_term_from_dates(policy_data: dict) -> float | None:
    """
    Best-effort policy term (in years) from ISO start/end dates when the extractor
    didn't capture policy_term_years directly.

    Returns:
        Term in years (float) or None if the dates are missing/unparseable.
    """
    start = policy_data.get("policy_start_date")
    end = policy_data.get("policy_end_date")
    if not start or not end:
        return None
    try:
        start_date = date.fromisoformat(str(start)[:10])
        end_date = date.fromisoformat(str(end)[:10])
    except ValueError:
        return None
    years = (end_date - start_date).days / 365.25
    return round(years, 2) if years > 0 else None


def _base_result(verdict: str, plain_english: str, extra: dict | None = None) -> dict:
    """
    Build a FinancialVerdict with every promised key present.

    Numeric/display fields default to null; callers overlay whatever they computed.
    """
    result = {
        "status": "success",
        "total_premium_paid": None,
        "maturity_benefit": None,
        "net_gain_loss": None,
        "effective_annual_return_pct": None,
        "fd_benchmark_return": None,
        "index_fund_benchmark_return": None,
        "fd_benchmark_pct": None,
        "index_fund_benchmark_pct": None,
        "verdict": verdict,
        "verdict_plain_english": plain_english,
        "comparison_statement": "",
    }
    if extra:
        result.update(extra)
    return result


def _build_financial_prompt(
    policy_data: dict, metrics: dict, policy_term_years: float, pay_term_years: float
) -> str:
    """
    Assemble the interpretation prompt. The numbers are already final — Gemini is
    explicitly told NOT to recompute them, only to explain them.

    Args:
        policy_data: Output dict from run_policy_extractor_agent
        metrics: Deterministic figures from build_financial_verdict
        policy_term_years: Full policy duration (growth horizon)
        pay_term_years: Years premiums are actually paid (may be shorter — limited-pay)

    Returns:
        Prompt string to send to Gemini
    """
    policy_type_hint = policy_data.get("insurer_name") or "this"
    # Only call out the limited-pay structure when it actually differs, so the
    # narrative can explain "you pay for X years, covered for Y" where relevant.
    if pay_term_years and pay_term_years < policy_term_years:
        term_line = (
            f"Premium-paying term: {pay_term_years:g} years (LIMITED-PAY — premiums "
            f"stop after this), while cover/growth runs the full {policy_term_years:g} years\n"
        )
    else:
        term_line = f"Policy term: {policy_term_years:g} years\n"
    return (
        "Interpret these ALREADY-COMPUTED figures for a policyholder. Do not "
        "recalculate or change any number — only explain what they mean.\n\n"
        f"Insurer: {policy_type_hint}\n"
        f"{term_line}"
        f"Total premium paid over the term: {metrics['total_premium_paid']}\n"
        f"Maturity benefit received: {metrics['maturity_benefit']}\n"
        f"Net gain/loss: {metrics['net_gain_loss']}\n"
        f"Effective annual return (CAGR): {metrics['effective_annual_return_pct']}%\n"
        f"Same premiums in a {metrics['fd_benchmark_pct']}% fixed deposit would grow to "
        f"{metrics['fd_benchmark_return']}\n"
        f"Same premiums in a {metrics['index_fund_benchmark_pct']}% index fund would grow to "
        f"{metrics['index_fund_benchmark_return']}\n"
        f"Calculator verdict: {metrics['verdict']}\n\n"
        "Return ONLY JSON with exactly these two keys:\n"
        '{ "verdict_plain_english": "1-2 sentences a non-financial person understands", '
        '"comparison_statement": "1 sentence contrasting this policy against the FD / index fund benchmark" }'
    )


def run_financial_evaluator_agent(policy_data: dict) -> dict:
    """
    Main entry point for the Financial Evaluator Agent.

    Steps:
    1. Parse premium / term / maturity out of the (string-typed) policy data
    2. If premium or term is unknown → return an INSUFFICIENT_DATA verdict (no LLM call)
    3. Compute total premium paid
    4. If there is no maturity benefit (pure term / most health cover) → return a
       NO_MATURITY_BENEFIT verdict explaining it's protection, not an investment
    5. Otherwise compute the full verdict deterministically, then ask Gemini to
       write the plain-English narrative around those fixed numbers

    Args:
        policy_data: Output dict from run_policy_extractor_agent (Agent 2)

    Returns:
        FinancialVerdict dict with status + all metric fields + narrative

    Raises:
        ValueError: If Gemini returns unparseable JSON
        RuntimeError: On Gemini API failure after retries
    """
    logger.info("Financial Evaluator Agent starting")

    # ── Step 1: Parse the raw string fields into numbers ──────────────────────
    premium = parse_currency_to_float(policy_data.get("premium_amount"))
    maturity = parse_currency_to_float(policy_data.get("maturity_benefit"))
    # policy_term = full duration of cover → the growth HORIZON for CAGR/benchmarks.
    policy_term = parse_term_years(policy_data.get("policy_term_years")) or _derive_term_from_dates(policy_data)
    # pay_term = years premiums are actually PAID → drives total premium. Falls back
    # to the policy term for regular-pay plans, and is capped at it (you can't pay
    # premiums for longer than the policy runs — guards against a bad extraction).
    pay_term = parse_term_years(policy_data.get("premium_paying_term_years"))
    if pay_term is None or (policy_term is not None and pay_term > policy_term):
        pay_term = policy_term
    frequency = policy_data.get("premium_frequency") or "annual"
    currency = detect_currency_symbol(
        policy_data.get("premium_amount"), policy_data.get("maturity_benefit"),
        policy_data.get("sum_assured"),
    )

    # ── Step 2: Can we even compute total premium? ────────────────────────────
    if premium is None or policy_term is None:
        logger.warning(
            f"Financial Evaluator: insufficient data (premium={premium}, term={policy_term}) — "
            "returning INSUFFICIENT_DATA without an LLM call"
        )
        return _base_result(
            "INSUFFICIENT_DATA",
            "We couldn't find a clear premium amount and policy term in this document, "
            "so a return calculation isn't possible. Check the policy schedule for these figures.",
        )

    # ── Step 3: Total premium paid over the PREMIUM-PAYING term ────────────────
    total_premium = calculate_total_premium(premium, frequency, pay_term)

    # ── Step 4: No maturity benefit → not an investment product ───────────────
    if maturity is None or maturity <= 0:
        logger.info("Financial Evaluator: no maturity benefit — protection-only policy")
        return _base_result(
            "NO_MATURITY_BENEFIT",
            "This policy has no maturity payout — it is pure protection, not an "
            "investment, so there is no return to compare. You pay for cover, not for growth.",
            extra={"total_premium_paid": f"{currency}{total_premium:,.0f}"},
        )

    # ── Step 5: Full deterministic verdict + Gemini narrative ─────────────────
    # Growth compounds over the full policy term even after premiums stop, so the
    # HORIZON is policy_term — not pay_term.
    metrics = build_financial_verdict(total_premium, maturity, policy_term, currency)

    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=settings.GEMINI_MODEL,
        system_instruction=FINANCIAL_EVALUATOR_SYSTEM_PROMPT,
    )

    logger.info("Calling Gemini to interpret financial metrics...")
    prompt = _build_financial_prompt(policy_data, metrics, policy_term, pay_term)
    raw_response = call_gemini_with_retry(model, prompt, FINANCIAL_EVALUATOR_SYSTEM_PROMPT)
    narrative = parse_gemini_json_response(raw_response)

    # Numbers come from the calculator (authoritative); prose comes from Gemini.
    result = {"status": "success"}
    result.update({field: metrics[field] for field in _METRIC_FIELDS})
    result["verdict_plain_english"] = narrative.get("verdict_plain_english") or ""
    result["comparison_statement"] = narrative.get("comparison_statement") or ""

    logger.info(
        f"Financial Evaluator Agent complete — verdict: {result['verdict']} "
        f"({result['effective_annual_return_pct']}% CAGR)"
    )
    return result


# ─── ADK Agent Definition ────────────────────────────────────────────────────

def create_financial_evaluator_agent() -> LlmAgent:
    """
    Create and return the ADK LlmAgent for financial evaluation.
    Called by pipeline.py during pipeline construction.

    Returns:
        Configured ADK LlmAgent instance
    """
    evaluator_tool = FunctionTool(
        func=run_financial_evaluator_agent,
        name="evaluate_financials",
        description=(
            "Computes total premium paid, effective annual return (CAGR), and "
            "fixed-deposit / index-fund benchmarks for an insurance policy, then "
            "returns a PROFIT / BREAK_EVEN / NET_LOSS verdict in plain English."
        ),
    )

    agent = LlmAgent(
        name="FinancialEvaluatorAgent",
        model=settings.GEMINI_MODEL,
        description="Agent 4: Judges whether the policy is financially worth holding.",
        tools=[evaluator_tool],
    )

    logger.info("FinancialEvaluatorAgent created")
    return agent
