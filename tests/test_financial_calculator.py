"""
InsureIQ — Tests: Financial Calculator (Agent 4's ADK tool)
Run with: pytest tests/test_financial_calculator.py -v

Pure arithmetic — NO Gemini, NO mocks, NO API key. These assert the numbers a
customer sees are correct and deterministic.
"""

import math
import pytest

from tools.financial_calculator import (
    parse_currency_to_float,
    detect_currency_symbol,
    parse_term_years,
    calculate_total_premium,
    calculate_cagr,
    calculate_fd_maturity,
    build_financial_verdict,
)


class TestParseCurrencyToFloat:
    def test_indian_grouping(self):
        assert parse_currency_to_float("₹5,00,000") == 500000.0

    def test_dollar_grouping(self):
        assert parse_currency_to_float("$50,000") == 50000.0

    def test_rupee_prefix_word(self):
        assert parse_currency_to_float("Rs.15,000") == 15000.0

    def test_lakh_magnitude(self):
        assert parse_currency_to_float("10 Lakhs") == 1_000_000.0

    def test_crore_magnitude(self):
        assert parse_currency_to_float("1.5 Crore") == 15_000_000.0

    def test_plain_number_passthrough(self):
        assert parse_currency_to_float(480000) == 480000.0
        assert parse_currency_to_float(2000.5) == 2000.5

    def test_decimal_amount(self):
        assert parse_currency_to_float("₹5,00,000.50") == 500000.50

    def test_none_and_empty_return_none(self):
        assert parse_currency_to_float(None) is None
        assert parse_currency_to_float("") is None
        assert parse_currency_to_float("not a number") is None


class TestDetectCurrencySymbol:
    def test_rupee(self):
        assert detect_currency_symbol("₹5,00,000") == "₹"
        assert detect_currency_symbol("Rs. 15000") == "₹"
        assert detect_currency_symbol("INR 500000") == "₹"

    def test_dollar(self):
        assert detect_currency_symbol("$50,000") == "$"

    def test_defaults_to_rupee(self):
        assert detect_currency_symbol(None, "500000") == "₹"

    def test_first_recognizable_wins(self):
        assert detect_currency_symbol(None, "$50,000", "₹5,00,000") == "$"


class TestParseTermYears:
    def test_plain_number(self):
        assert parse_term_years(20) == 20.0

    def test_string_with_word(self):
        assert parse_term_years("20 years") == 20.0

    def test_hyphenated(self):
        assert parse_term_years("15-year") == 15.0

    def test_invalid_returns_none(self):
        assert parse_term_years(None) is None
        assert parse_term_years("lifetime") is None
        assert parse_term_years(0) is None


class TestCalculateTotalPremium:
    def test_monthly(self):
        # ₹2,000/month for 20 years = ₹4,80,000
        assert calculate_total_premium(2000, "monthly", 20) == 480000

    def test_annual(self):
        assert calculate_total_premium(15000, "annual", 10) == 150000

    def test_quarterly(self):
        assert calculate_total_premium(5000, "quarterly", 5) == 100000

    def test_unknown_frequency_defaults_annual(self):
        assert calculate_total_premium(1000, "fortnightly", 3) == 3000

    def test_single_premium_is_lump_sum(self):
        # A single-premium policy is one payment regardless of term.
        assert calculate_total_premium(100000, "single", 20) == 100000

    def test_limited_pay_uses_paying_term(self):
        # Limited-pay: ₹50,000/year paid for only 10 years = ₹5,00,000, regardless
        # of how long the policy itself runs. The third arg is the PAYING term.
        assert calculate_total_premium(50000, "annual", 10) == 500000


class TestCalculateCagr:
    def test_growth(self):
        # 100000 → 200000 over 10 years ≈ 7.18%
        cagr = calculate_cagr(100000, 200000, 10)
        assert cagr == pytest.approx(0.0718, abs=1e-4)

    def test_negative_return(self):
        cagr = calculate_cagr(200000, 150000, 5)
        assert cagr < 0

    def test_invalid_inputs_return_none(self):
        assert calculate_cagr(0, 100000, 10) is None
        assert calculate_cagr(100000, 0, 10) is None
        assert calculate_cagr(100000, 100000, 0) is None


class TestCalculateFdMaturity:
    def test_compound_interest(self):
        # 100000 at 6% for 10 years
        expected = 100000 * (1.06 ** 10)
        assert calculate_fd_maturity(100000, 0.06, 10) == pytest.approx(expected)

    def test_zero_years_returns_principal(self):
        assert calculate_fd_maturity(100000, 0.06, 0) == 100000


class TestBuildFinancialVerdict:
    def test_profit_verdict(self):
        # 100000 → 300000 over 10 years ≈ 11.6% CAGR → PROFIT
        result = build_financial_verdict(100000, 300000, 10)
        assert result["verdict"] == "PROFIT"
        assert result["effective_annual_return_pct"] > 8

    def test_break_even_verdict(self):
        # ~5% CAGR lands in the 4–8% break-even band
        result = build_financial_verdict(100000, 163000, 10)
        assert result["verdict"] == "BREAK_EVEN"

    def test_net_loss_verdict(self):
        # 480000 → 600000 over 20 years ≈ 1.1% CAGR → NET_LOSS
        result = build_financial_verdict(480000, 600000, 20)
        assert result["verdict"] == "NET_LOSS"

    def test_unknown_when_cagr_undefined(self):
        result = build_financial_verdict(0, 100000, 10)
        assert result["verdict"] == "UNKNOWN"
        assert result["effective_annual_return_pct"] == 0

    def test_display_strings_and_benchmarks(self):
        result = build_financial_verdict(480000, 600000, 20, currency_symbol="₹")
        assert result["total_premium_paid"] == "₹480,000"
        assert result["maturity_benefit"] == "₹600,000"
        assert result["net_gain_loss"] == "₹+120,000"
        assert result["fd_benchmark_pct"] == 6.0
        assert result["index_fund_benchmark_pct"] == 12.0
        # FD at 6% on 480k over 20y comfortably beats this policy's 600k payout.
        assert parse_currency_to_float(result["fd_benchmark_return"]) > 600000

    def test_net_loss_shows_negative_sign(self):
        result = build_financial_verdict(500000, 400000, 10)
        assert result["net_gain_loss"].startswith("₹-")
