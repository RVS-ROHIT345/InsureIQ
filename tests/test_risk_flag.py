"""
InsureIQ — Tests: Risk Flag Agent (Agent 5)
Run with: pytest tests/test_risk_flag.py -v

Gemini is mocked so these run without a real API key — safe for CI. The key
assertions verify severity counts are recomputed from the flags, not trusted
from whatever Gemini returned.
"""

import pytest
from unittest.mock import patch, MagicMock

from agents.risk_flag_agent import (
    run_risk_flag_agent,
    _build_risk_prompt,
    _normalize_risk_flags,
)


INGESTION_RESULT = {
    "status": "success",
    "document_type": "life",
    "sections": {
        "exclusions": "Suicide within 12 months is excluded.",
        "terms_and_conditions": "Policy auto-renews unless cancelled 30 days prior.",
        "maturity_clause": "Maturity at age 99.",
    },
    "raw_text": "Life insurance policy with auto-renewal and surrender penalties.",
}

# Note the deliberately WRONG totals from Gemini — the agent must ignore them and
# recompute from the flags list (2 HIGH, 1 MEDIUM, 0 LOW → overall HIGH).
MOCK_GEMINI_RESPONSE = """{
  "flags": [
    {"severity": "MEDIUM", "category": "Auto-renewal", "description": "Auto renews", "implication": "You may keep paying", "page_reference": "p3"},
    {"severity": "HIGH", "category": "Surrender penalty", "description": "Lose money early", "implication": "Big loss if you exit", "page_reference": "p5"},
    {"severity": "HIGH", "category": "Maturity age", "description": "Matures at 99", "implication": "You may never see it", "page_reference": "p7"}
  ],
  "total_high": 5,
  "total_medium": 9,
  "total_low": 2,
  "overall_risk_level": "LOW"
}"""


def _mock_model(response_text):
    model = MagicMock()
    model.generate_content.return_value.text = response_text
    return model


class TestBuildRiskPrompt:
    def test_includes_all_sections(self):
        prompt = _build_risk_prompt(INGESTION_RESULT)
        assert "EXCLUSIONS" in prompt
        assert "TERMS_AND_CONDITIONS" in prompt
        assert "MATURITY_CLAUSE" in prompt
        assert "life insurance" in prompt

    def test_falls_back_to_raw_text(self):
        result = {"document_type": "car", "sections": {}, "raw_text": "Raw fallback trap text"}
        prompt = _build_risk_prompt(result)
        assert "Raw fallback trap text" in prompt


class TestNormalizeRiskFlags:
    def test_counts_recomputed_from_flags(self):
        normalized = _normalize_risk_flags(
            {"flags": [{"severity": "HIGH"}, {"severity": "HIGH"}, {"severity": "MEDIUM"}],
             "total_high": 99, "overall_risk_level": "LOW"}
        )
        assert normalized["total_high"] == 2
        assert normalized["total_medium"] == 1
        assert normalized["total_low"] == 0
        assert normalized["overall_risk_level"] == "HIGH"

    def test_sorted_worst_first(self):
        normalized = _normalize_risk_flags(
            {"flags": [{"severity": "LOW"}, {"severity": "HIGH"}, {"severity": "MEDIUM"}]}
        )
        severities = [f["severity"] for f in normalized["flags"]]
        assert severities == ["HIGH", "MEDIUM", "LOW"]

    def test_unknown_severity_becomes_low_not_dropped(self):
        normalized = _normalize_risk_flags({"flags": [{"severity": "CRITICAL"}]})
        assert len(normalized["flags"]) == 1
        assert normalized["flags"][0]["severity"] == "LOW"

    def test_empty_flags_overall_none(self):
        normalized = _normalize_risk_flags({})
        assert normalized["flags"] == []
        assert normalized["overall_risk_level"] == "NONE"

    def test_single_dict_flag_wrapped(self):
        normalized = _normalize_risk_flags({"flags": {"severity": "HIGH"}})
        assert len(normalized["flags"]) == 1

    def test_missing_flag_fields_defaulted(self):
        normalized = _normalize_risk_flags({"flags": [{"severity": "HIGH"}]})
        flag = normalized["flags"][0]
        assert flag["category"] == "Uncategorized"
        assert flag["description"] == ""
        assert flag["page_reference"] == ""

    def test_market_norm_carried_and_counted(self):
        normalized = _normalize_risk_flags({"flags": [
            {"severity": "HIGH", "market_norm": "unusual"},
            {"severity": "HIGH", "market_norm": "standard"},
            {"severity": "LOW", "market_norm": "UNUSUAL"},  # case-insensitive
        ]})
        norms = [f["market_norm"] for f in normalized["flags"]]
        assert norms.count("unusual") == 2
        assert norms.count("standard") == 1
        assert normalized["total_unusual"] == 2

    def test_missing_or_invalid_market_norm_defaults_to_standard(self):
        # A missing or unrecognised value must NOT inflate the switch case.
        normalized = _normalize_risk_flags({"flags": [
            {"severity": "HIGH"},                              # missing
            {"severity": "MEDIUM", "market_norm": "typical"},  # invalid
        ]})
        assert all(f["market_norm"] == "standard" for f in normalized["flags"])
        assert normalized["total_unusual"] == 0


class TestRunRiskFlagAgent:
    @patch("agents.risk_flag_agent.genai")
    def test_successful_scan_recomputes_counts(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model(MOCK_GEMINI_RESPONSE)
        mock_genai.configure = MagicMock()

        result = run_risk_flag_agent(INGESTION_RESULT)

        assert result["status"] == "success"
        assert len(result["flags"]) == 3
        # Gemini claimed 5/9/2 & LOW — agent must correct to the real 2/1/0 & HIGH.
        assert result["total_high"] == 2
        assert result["total_medium"] == 1
        assert result["total_low"] == 0
        assert result["overall_risk_level"] == "HIGH"
        assert result["flags"][0]["severity"] == "HIGH"

    @patch("agents.risk_flag_agent.genai")
    def test_empty_response_is_no_risk(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model("{}")
        mock_genai.configure = MagicMock()

        result = run_risk_flag_agent(INGESTION_RESULT)

        assert result["flags"] == []
        assert result["overall_risk_level"] == "NONE"

    @patch("agents.risk_flag_agent.genai")
    def test_invalid_json_raises(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model("garbage")
        mock_genai.configure = MagicMock()

        with pytest.raises(ValueError, match="invalid JSON"):
            run_risk_flag_agent(INGESTION_RESULT)
