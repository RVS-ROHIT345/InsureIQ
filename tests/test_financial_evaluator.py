"""
InsureIQ — Tests: Financial Evaluator Agent (Agent 4)
Run with: pytest tests/test_financial_evaluator.py -v

Gemini is mocked so these run without a real API key — safe for CI. The numeric
verdict is deterministic (calculator), so we assert Gemini is only used for prose.
"""

import pytest
from unittest.mock import patch, MagicMock

from agents.financial_evaluator_agent import (
    run_financial_evaluator_agent,
    _derive_term_from_dates,
    _derive_horizon_from_maturity,
    _build_financial_prompt,
)


# An endowment-style policy that clearly loses to inflation.
POLICY_DATA = {
    "status": "success",
    "insurer_name": "Acme Life",
    "premium_amount": "₹24,000",
    "premium_frequency": "annual",
    "policy_term_years": "20",
    "maturity_benefit": "₹6,00,000",
    "sum_assured": "₹5,00,000",
    "policy_start_date": "2020-01-01",
    "policy_end_date": "2040-01-01",
}

MOCK_NARRATIVE = """{
  "verdict_plain_english": "You pay in more than inflation-adjusted value; this policy barely grows your money.",
  "comparison_statement": "The same premiums in a fixed deposit would have returned far more."
}"""


def _mock_model(response_text):
    model = MagicMock()
    model.generate_content.return_value.text = response_text
    return model


class TestDeriveTermFromDates:
    def test_derives_twenty_years(self):
        assert _derive_term_from_dates(POLICY_DATA) == pytest.approx(20.0, abs=0.05)

    def test_missing_dates_return_none(self):
        assert _derive_term_from_dates({"policy_start_date": "2020-01-01"}) is None

    def test_bad_dates_return_none(self):
        assert _derive_term_from_dates(
            {"policy_start_date": "garbage", "policy_end_date": "2040-01-01"}
        ) is None


class TestDeriveHorizonFromMaturity:
    def test_derives_ten_year_horizon(self):
        horizon = _derive_horizon_from_maturity(
            {"policy_start_date": "2026-07-01", "maturity_date": "2036-07-01"}
        )
        assert horizon == pytest.approx(10.0, abs=0.05)

    def test_missing_maturity_date_returns_none(self):
        assert _derive_horizon_from_maturity({"policy_start_date": "2026-07-01"}) is None

    def test_maturity_on_or_before_start_returns_none(self):
        assert _derive_horizon_from_maturity(
            {"policy_start_date": "2026-07-01", "maturity_date": "2026-07-01"}
        ) is None

    def test_implausibly_long_span_returns_none(self):
        # A mis-parsed date centuries out must not become the horizon.
        assert _derive_horizon_from_maturity(
            {"policy_start_date": "2026-07-01", "maturity_date": "2500-07-01"}
        ) is None

    def test_garbage_date_returns_none(self):
        assert _derive_horizon_from_maturity(
            {"policy_start_date": "2026-07-01", "maturity_date": "not-a-date"}
        ) is None


class TestBuildFinancialPrompt:
    def test_tells_model_not_to_recompute(self):
        metrics = {
            "total_premium_paid": "₹480,000", "maturity_benefit": "₹600,000",
            "net_gain_loss": "₹+120,000", "effective_annual_return_pct": 1.12,
            "fd_benchmark_return": "₹1,539,000", "index_fund_benchmark_return": "₹4,632,000",
            "fd_benchmark_pct": 6.0, "index_fund_benchmark_pct": 12.0, "verdict": "NET_LOSS",
        }
        prompt = _build_financial_prompt(POLICY_DATA, metrics, 20, 20)
        assert "Do not" in prompt or "do not" in prompt
        assert "₹480,000" in prompt
        assert "NET_LOSS" in prompt

    def test_flags_limited_pay_in_prompt(self):
        metrics = {
            "total_premium_paid": "₹500,000", "maturity_benefit": "₹1,500,000",
            "net_gain_loss": "₹+1,000,000", "effective_annual_return_pct": 5.6,
            "fd_benchmark_return": "₹1,600,000", "index_fund_benchmark_return": "₹4,800,000",
            "fd_benchmark_pct": 6.0, "index_fund_benchmark_pct": 12.0, "verdict": "BREAK_EVEN",
        }
        # Pay for 10 years, covered for 20 → prompt must call out the limited-pay split.
        prompt = _build_financial_prompt(POLICY_DATA, metrics, 20, 10)
        assert "LIMITED-PAY" in prompt
        assert "10 years" in prompt


class TestRunFinancialEvaluatorAgent:
    @patch("agents.financial_evaluator_agent.genai")
    def test_full_verdict_merges_numbers_and_prose(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model(MOCK_NARRATIVE)
        mock_genai.configure = MagicMock()

        result = run_financial_evaluator_agent(POLICY_DATA, document_type="life")

        assert result["status"] == "success"
        # 24000/year × 20 years = 480,000 — deterministic, not from Gemini.
        assert result["total_premium_paid"] == "₹480,000"
        assert result["maturity_benefit"] == "₹600,000"
        assert result["verdict"] == "NET_LOSS"
        # Narrative comes from the mocked Gemini call.
        assert "inflation" in result["verdict_plain_english"]
        assert result["comparison_statement"].startswith("The same premiums")

    @patch("agents.financial_evaluator_agent.genai")
    def test_insufficient_data_skips_gemini(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model(MOCK_NARRATIVE)
        mock_genai.configure = MagicMock()

        result = run_financial_evaluator_agent({"premium_amount": None, "policy_term_years": None})

        assert result["verdict"] == "INSUFFICIENT_DATA"
        assert result["total_premium_paid"] is None
        # No Gemini call should have been made.
        mock_genai.GenerativeModel.return_value.generate_content.assert_not_called()

    @patch("agents.financial_evaluator_agent.genai")
    def test_limited_pay_uses_paying_term_not_policy_term(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model(MOCK_NARRATIVE)
        mock_genai.configure = MagicMock()

        # Pay ₹50,000/year for 10 years, but covered/growing for 20 years.
        limited_pay = {
            "insurer_name": "Acme Life",
            "premium_amount": "₹50,000", "premium_frequency": "annual",
            "policy_term_years": "20", "premium_paying_term_years": "10",
            "maturity_benefit": "₹15,00,000",
        }
        result = run_financial_evaluator_agent(limited_pay, document_type="life")

        # Total premium is 50,000 × 10 = ₹500,000 (NOT × 20 = ₹1,000,000).
        assert result["total_premium_paid"] == "₹500,000"
        # IRR of the 10-year premium stream grown over the full 20-year horizon
        # (≈ 7% — premiums stop early, then keep compounding) → BREAK_EVEN, not the
        # NET_LOSS the old (paying-for-20-years) calculation would have produced.
        assert result["verdict"] == "BREAK_EVEN"

    @patch("agents.financial_evaluator_agent.genai")
    def test_maturity_date_overrides_mis_extracted_term(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model(MOCK_NARRATIVE)
        mock_genai.configure = MagicMock()

        # An endowment where the extractor grabbed a 1-year renewal term, but the
        # maturity_date reveals the real 10-year horizon. The IRR must use the
        # maturity-date horizon (10y) — NOT policy_term_years (1y), which would give
        # an absurd ~1400% "return" on a single year's premium.
        mismatched = {
            "insurer_name": "Acme Life",
            "premium_amount": "₹100,000", "premium_frequency": "annual",
            "policy_term_years": "1", "premium_paying_term_years": "10",
            "maturity_benefit": "₹15,00,000",
            "policy_start_date": "2026-01-01", "maturity_date": "2036-01-01",
        }
        result = run_financial_evaluator_agent(mismatched, document_type="life")

        # Paying term re-derived to the full 10 years → 100,000 × 10 = ₹1,000,000
        # (proves the horizon fix; the buggy path would show ₹100,000 for 1 year).
        assert result["total_premium_paid"] == "₹1,000,000"
        # IRR of that 10-year stream growing to ₹1.5M is a sane ~7%, not ~1400%.
        assert 4.0 <= result["effective_annual_return_pct"] <= 8.0
        assert result["verdict"] == "BREAK_EVEN"

    @patch("agents.financial_evaluator_agent.genai")
    def test_paying_term_capped_at_policy_term(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model(MOCK_NARRATIVE)
        mock_genai.configure = MagicMock()

        # A bad extraction: paying term longer than the policy runs → cap at policy term.
        bad = dict(POLICY_DATA)
        bad["premium_paying_term_years"] = "40"  # policy_term is 20
        result = run_financial_evaluator_agent(bad, document_type="life")
        # Capped to 20 years → 24,000 × 20 = ₹480,000, same as regular-pay.
        assert result["total_premium_paid"] == "₹480,000"

    @patch("agents.financial_evaluator_agent.genai")
    def test_no_maturity_benefit_is_protection_only(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model(MOCK_NARRATIVE)
        mock_genai.configure = MagicMock()

        term_policy = {
            "premium_amount": "₹12,000", "premium_frequency": "annual",
            "policy_term_years": "30", "maturity_benefit": None,
        }
        result = run_financial_evaluator_agent(term_policy, document_type="life")

        assert result["verdict"] == "NO_MATURITY_BENEFIT"
        assert result["total_premium_paid"] == "₹360,000"
        mock_genai.GenerativeModel.return_value.generate_content.assert_not_called()

    @patch("agents.financial_evaluator_agent.genai")
    def test_term_derived_from_dates_when_missing(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model(MOCK_NARRATIVE)
        mock_genai.configure = MagicMock()

        no_term = dict(POLICY_DATA)
        no_term["policy_term_years"] = None  # force fallback to date derivation
        result = run_financial_evaluator_agent(no_term, document_type="life")

        assert result["status"] == "success"
        assert result["total_premium_paid"] == "₹480,000"

    @patch("agents.financial_evaluator_agent.genai")
    def test_invalid_json_raises(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model("garbage")
        mock_genai.configure = MagicMock()

        with pytest.raises(ValueError, match="invalid JSON"):
            run_financial_evaluator_agent(POLICY_DATA, document_type="life")

    @patch("agents.financial_evaluator_agent.genai")
    def test_non_life_product_is_protection_only(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model(MOCK_NARRATIVE)
        mock_genai.configure = MagicMock()

        # A home policy that carries a stray "maturity" figure (e.g. a rider refund
        # clause). It must NOT be run through the IRR/loss analysis meant for life
        # plans — that's what wrongly told a customer to cancel their home cover.
        home_policy = {
            "insurer_name": "Meridian Shield",
            "premium_amount": "$2,070", "premium_frequency": "annual",
            "policy_term_years": "1", "maturity_benefit": "$1,100",
        }
        result = run_financial_evaluator_agent(home_policy, document_type="home")

        assert result["verdict"] == "PROTECTION_ONLY"
        # Total premium is still reported; investment-only fields stay null.
        assert result["total_premium_paid"] == "$2,070"
        assert result["effective_annual_return_pct"] is None
        assert result["net_gain_loss"] is None
        # No IRR verdict means no Gemini narrative call.
        mock_genai.GenerativeModel.return_value.generate_content.assert_not_called()

    @patch("agents.financial_evaluator_agent.genai")
    def test_unknown_type_without_maturity_is_protection_only(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model(MOCK_NARRATIVE)
        mock_genai.configure = MagicMock()

        # An unknown-type protection policy with NO maturity payout → conservatively
        # protection-only, never a spurious loss verdict, no Gemini call.
        protection = {
            "premium_amount": "₹12,000", "premium_frequency": "annual",
            "policy_term_years": "1", "maturity_benefit": None,
        }
        result = run_financial_evaluator_agent(protection)  # document_type defaults to "unknown"

        assert result["verdict"] == "PROTECTION_ONLY"
        mock_genai.GenerativeModel.return_value.generate_content.assert_not_called()

    @patch("agents.financial_evaluator_agent.genai")
    def test_health_endowment_gets_investment_analysis(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model(MOCK_NARRATIVE)
        mock_genai.configure = MagicMock()

        # A health-cum-savings ENDOWMENT tagged `health` by Agent 1. Despite not being
        # `life`, its genuine maturity benefit (₹18.5L ≥ ₹10.4L premiums) must trigger
        # the IRR analysis — otherwise its dismal ~1.6% return is hidden behind a
        # PROTECTION_ONLY verdict. (Mirrors sample_health_insurance_policy.docx.)
        endowment = {
            "insurer_name": "Sentinel Life & Health",
            "premium_amount": "₹52,000", "premium_frequency": "annual",
            "policy_term_years": "45", "premium_paying_term_years": "20",
            "maturity_benefit": "₹18,50,000",
            "policy_start_date": "2019-04-10", "maturity_date": "2064-04-10",
        }
        result = run_financial_evaluator_agent(endowment, document_type="health")

        # Premiums = 52,000 × 20 = ₹1,040,000 (paying term, not the 45y horizon).
        assert result["total_premium_paid"] == "₹1,040,000"
        assert result["maturity_benefit"] == "₹1,850,000"
        # A lump sum barely above premiums over 45 years is a clear loss vs benchmarks.
        assert result["verdict"] == "NET_LOSS"
        assert result["effective_annual_return_pct"] < 3.0
        # Genuine investment analysis → Gemini IS asked to write the narrative.
        mock_genai.GenerativeModel.return_value.generate_content.assert_called_once()
