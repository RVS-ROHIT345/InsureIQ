"""
InsureIQ — Financial Calculator Utility
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Registered as an ADK tool for the Financial Evaluator Agent (Agent 4).

This module performs real arithmetic — NOT LLM prompting. All numbers a customer
sees originate here, deterministically. The Financial Evaluator Agent calls these
functions, then hands the results to Gemini purely for plain-English interpretation.
Keeping the maths out of the LLM guarantees the numbers can't hallucinate.

Kaggle concept demonstrated: Agent Skills — a deterministic tool the agent invokes.
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Benchmark rates used to answer "what else could this money have done?"
FD_BENCHMARK_RATE = 0.06     # ~6% — a conservative fixed deposit
INDEX_BENCHMARK_RATE = 0.12  # ~12% — a long-run broad equity index fund

# Payments per year for each supported premium frequency.
PAYMENTS_PER_YEAR = {
    "monthly": 12,
    "quarterly": 4,
    "semi-annual": 2,
    "semiannual": 2,
    "half-yearly": 2,
    "annual": 1,
    "annually": 1,
    "yearly": 1,
    "single": 1,      # single-premium policy — one payment up front
    "one-time": 1,
}

# Indian-notation magnitude words. Insurance docs frequently write "10 Lakhs" /
# "1.5 Crore" instead of the full figure — expand them to a plain number.
_MAGNITUDE = [
    ("crore", 1e7),
    ("cr", 1e7),
    ("lakh", 1e5),
    ("lac", 1e5),
]


# ─── Parsing helpers ──────────────────────────────────────────────────────────
# The Policy Extractor (Agent 2) emits currency/term values as *strings* with
# whatever formatting the document used ("₹5,00,000", "10 Lakhs", "20 years").
# These helpers turn that free text into clean floats the maths below can use.

def parse_currency_to_float(value) -> Optional[float]:
    """
    Convert a currency string to a float.

    Handles Indian grouping ("5,00,000"), currency symbols/codes ("₹", "Rs.",
    "$", "INR"), and magnitude words ("10 Lakhs" → 1_000_000, "1.5 Cr" → 15_000_000).

    Args:
        value: A number, or a string like "₹5,00,000" / "10 Lakhs" / "$50,000".

    Returns:
        The parsed amount as a float, or None if nothing numeric could be found.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip().lower()
    if not text:
        return None

    multiplier = 1.0
    for word, factor in _MAGNITUDE:
        if word in text:
            multiplier = factor
            break

    # Grab the first numeric token, then drop grouping commas.
    match = re.search(r"[-+]?\d[\d,]*\.?\d*", text)
    if not match:
        return None

    try:
        number = float(match.group().replace(",", ""))
    except ValueError:
        return None

    return number * multiplier


def detect_currency_symbol(*values) -> str:
    """
    Guess the display currency symbol from any of the given raw strings.

    Args:
        *values: Candidate strings (e.g. premium_amount, maturity_benefit).

    Returns:
        A currency symbol for display. Defaults to "₹" (the primary audience is
        Indian insurance customers) when nothing recognizable is present.
    """
    for value in values:
        if value is None:
            continue
        text = str(value).lower()
        if "₹" in text or "rs" in text or "inr" in text:
            return "₹"
        if "$" in text or "usd" in text:
            return "$"
        if "£" in text or "gbp" in text:
            return "£"
        if "€" in text or "eur" in text:
            return "€"
    return "₹"


def parse_term_years(value) -> Optional[float]:
    """
    Convert a policy-term value to a number of years.

    Args:
        value: A number, or a string like "20" / "20 years" / "15-year".

    Returns:
        The term in years as a float, or None if not parseable.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None

    match = re.search(r"\d+\.?\d*", str(value))
    if not match:
        return None
    years = float(match.group())
    return years if years > 0 else None


# ─── Core arithmetic ──────────────────────────────────────────────────────────

def calculate_total_premium(
    premium_amount: float,
    premium_frequency: str,
    premium_paying_term_years: float,
) -> float:
    """
    Calculate total premium paid over the PREMIUM-PAYING term.

    Critically, this is driven by how many years premiums are actually paid — NOT
    the policy's full duration. For a regular-pay plan the two are equal; for a
    limited-pay plan (pay 10 years, covered 20) they differ, and using the policy
    term here would badly overstate what the customer paid.

    Args:
        premium_amount: Single premium payment amount (in any currency)
        premium_frequency: "monthly" | "quarterly" | "semi-annual" | "annual" | "single"
        premium_paying_term_years: Number of years premiums are actually paid

    Returns:
        Total amount paid across all premiums

    Example:
        ₹2,000/month paid for 20 years = ₹4,80,000 total
        ₹50,000/year paid for 10 years (limited-pay) = ₹5,00,000 total
    """
    frequency_key = (premium_frequency or "annual").strip().lower()
    payments_per_year = PAYMENTS_PER_YEAR.get(frequency_key, 1)

    # A single-premium policy is one lump payment regardless of term length.
    if payments_per_year == 1 and frequency_key in ("single", "one-time"):
        total = premium_amount
    else:
        total = premium_amount * payments_per_year * premium_paying_term_years

    logger.debug(
        f"Total premium: {total} ({payments_per_year} payments/year × "
        f"{premium_paying_term_years} paying years)"
    )
    return total


def calculate_cagr(
    principal: float,
    maturity_value: float,
    years: float,
) -> Optional[float]:
    """
    Calculate Compound Annual Growth Rate (CAGR).

    CAGR = (maturity_value / principal) ^ (1 / years) - 1

    Args:
        principal: Total amount invested (total premiums paid)
        maturity_value: Final payout at maturity
        years: Total investment duration in years

    Returns:
        CAGR as a decimal (e.g., 0.016 = 1.6%). Can be negative if the policy
        pays back less than was paid in. None if inputs make it undefined.
    """
    if principal <= 0 or maturity_value <= 0 or years <= 0:
        logger.warning("CAGR calculation skipped: invalid inputs")
        return None

    cagr = (maturity_value / principal) ** (1 / years) - 1
    logger.debug(f"CAGR: {cagr:.4f} ({cagr * 100:.2f}%)")
    return cagr


def calculate_fd_maturity(
    principal: float,
    annual_rate: float,
    years: float,
) -> float:
    """
    Calculate what a Fixed Deposit would return on the same principal.
    Used as benchmark comparison against insurance policy returns.

    Formula: A = P × (1 + r)^n  (compound interest, annual compounding)

    Args:
        principal: Initial lump sum (we use total premiums paid as proxy)
        annual_rate: FD interest rate as decimal (e.g., 0.06 for 6%)
        years: Investment duration in years

    Returns:
        Maturity amount from a fixed deposit
    """
    maturity = principal * ((1 + annual_rate) ** years)
    logger.debug(f"FD maturity at {annual_rate * 100:.1f}%: {maturity:.2f}")
    return maturity


# ─── Cash-flow model ──────────────────────────────────────────────────────────
# Premiums aren't paid as a lump sum on day one — they're a *stream* paid over the
# premium-paying term. Modelling that stream (rather than pretending the whole
# amount was invested up front) is what makes the policy return and the benchmarks
# realistic and mutually consistent.

def build_premium_schedule(
    premium_amount: float,
    premium_frequency: str,
    pay_term_years: float,
) -> list[tuple[float, float]]:
    """
    Build the actual premium payment stream as (time_in_years, amount) tuples.

    Payments are modelled as an annuity-due — each premium is paid at the START of
    its period (t = 0, 1/k, 2/k, …), which is how insurance premiums are actually
    collected. A single-premium policy is one payment at t = 0.

    Args:
        premium_amount: Amount of ONE premium payment
        premium_frequency: "monthly" | "quarterly" | "semi-annual" | "annual" | "single"
        pay_term_years: Years premiums are actually paid

    Returns:
        List of (time_years, amount) payments, earliest first.
    """
    frequency_key = (premium_frequency or "annual").strip().lower()
    payments_per_year = PAYMENTS_PER_YEAR.get(frequency_key, 1)

    if payments_per_year == 1 and frequency_key in ("single", "one-time"):
        return [(0.0, premium_amount)]

    n_payments = int(round(payments_per_year * (pay_term_years or 0)))
    interval = 1.0 / payments_per_year
    return [(i * interval, premium_amount) for i in range(n_payments)]


def future_value_of_stream(
    schedule: list[tuple[float, float]],
    annual_rate: float,
    horizon_years: float,
) -> float:
    """
    Future value at `horizon_years` of a payment stream invested at `annual_rate`.

    Each payment compounds from the moment it is made until the horizon, so money
    paid in year 1 grows longer than money paid in year 20. This is the correct
    "what if you'd invested the same premiums instead?" benchmark — an annuity's
    future value, not a lump sum sitting from day one.

    Args:
        schedule: (time_years, amount) payments from build_premium_schedule
        annual_rate: Growth rate as a decimal (e.g. 0.06)
        horizon_years: When the money is valued (the policy maturity date)

    Returns:
        Total future value of the stream at the horizon.
    """
    return sum(
        amount * ((1 + annual_rate) ** (horizon_years - t)) for t, amount in schedule
    )


def calculate_irr(
    schedule: list[tuple[float, float]],
    maturity_value: float,
    horizon_years: float,
) -> Optional[float]:
    """
    Money-weighted annual return (IRR) of the policy: the single rate at which the
    premium stream, compounded to the maturity horizon, equals the maturity payout.

    This replaces a naive lump-sum CAGR — because premiums are paid over time, a
    CAGR that assumes the whole amount was invested on day one understates the true
    return. IRR accounts for *when* each rupee was actually paid.

    Found by bisection: future_value_of_stream is strictly increasing in the rate,
    so a sign change is guaranteed to bracket exactly one root.

    Args:
        schedule: (time_years, amount) premium payments
        maturity_value: Payout received at horizon_years
        horizon_years: Policy maturity (growth horizon) in years

    Returns:
        IRR as a decimal (e.g. 0.0162 = 1.62%), possibly negative if the policy
        pays back less than was paid in. None if undefined.
    """
    total_paid = sum(amount for _, amount in schedule)
    if not schedule or maturity_value <= 0 or horizon_years <= 0 or total_paid <= 0:
        logger.warning("IRR calculation skipped: invalid inputs")
        return None

    def net(rate: float) -> float:
        return future_value_of_stream(schedule, rate, horizon_years) - maturity_value

    low, high = -0.9999, 10.0  # -99.99% to +1000% annual brackets any real policy
    net_low = net(low)
    if (net_low > 0) == (net(high) > 0):
        logger.warning("IRR calculation skipped: no sign change in bracket")
        return None

    for _ in range(100):
        mid = (low + high) / 2.0
        if (net(mid) > 0) == (net_low > 0):
            low = mid
        else:
            high = mid
        if high - low < 1e-10:
            break

    irr = (low + high) / 2.0
    logger.debug(f"IRR: {irr:.4f} ({irr * 100:.2f}%)")
    return irr


def build_financial_verdict(
    premium_amount: float,
    premium_frequency: str,
    pay_term_years: float,
    maturity_benefit: float,
    policy_term_years: float,
    currency_symbol: str = "₹",
) -> dict:
    """
    Master function: compute all financial metrics and return a verdict dict.
    This is what the Financial Evaluator Agent (Agent 4) calls as its ADK tool.

    Uses a cash-flow model throughout: the policy's return is the IRR of the actual
    premium stream, and the FD / index benchmarks are the future value of that SAME
    stream invested elsewhere. Policy and benchmarks are therefore computed on an
    identical, realistic basis — no lump-sum-on-day-one distortion.

    The verdict is derived from the effective annual return (IRR), not raw gain, so
    a policy that "grows" your money slower than inflation is correctly flagged.

    Args:
        premium_amount: Amount of ONE premium payment
        premium_frequency: Payment frequency ("annual", "monthly", "single", …)
        pay_term_years: Years premiums are actually paid (drives the stream length)
        maturity_benefit: Promised payout at maturity
        policy_term_years: Policy duration in years (the growth horizon)
        currency_symbol: Currency prefix for display strings

    Returns:
        Dict with all computed metrics and a PROFIT/BREAK_EVEN/NET_LOSS verdict
    """
    schedule = build_premium_schedule(premium_amount, premium_frequency, pay_term_years)
    total_premium = sum(amount for _, amount in schedule)
    net_gain_loss = maturity_benefit - total_premium

    irr = calculate_irr(schedule, maturity_benefit, policy_term_years)
    fd_return = future_value_of_stream(schedule, FD_BENCHMARK_RATE, policy_term_years)
    index_return = future_value_of_stream(schedule, INDEX_BENCHMARK_RATE, policy_term_years)

    if irr is None:
        verdict = "UNKNOWN"
    elif irr >= 0.08:        # 8%+ genuinely beats inflation and most safe options
        verdict = "PROFIT"
    elif irr >= 0.04:        # 4–8% roughly keeps pace with inflation
        verdict = "BREAK_EVEN"
    else:                    # under 4% (or negative) — money lost real value
        verdict = "NET_LOSS"

    return {
        "total_premium_paid": f"{currency_symbol}{total_premium:,.0f}",
        "maturity_benefit": f"{currency_symbol}{maturity_benefit:,.0f}",
        "net_gain_loss": f"{currency_symbol}{net_gain_loss:+,.0f}",
        "effective_annual_return_pct": round((irr or 0) * 100, 2),
        "fd_benchmark_return": f"{currency_symbol}{fd_return:,.0f}",
        "index_fund_benchmark_return": f"{currency_symbol}{index_return:,.0f}",
        "fd_benchmark_pct": round(FD_BENCHMARK_RATE * 100, 1),
        "index_fund_benchmark_pct": round(INDEX_BENCHMARK_RATE * 100, 1),
        "verdict": verdict,
    }
