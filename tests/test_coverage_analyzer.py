"""
InsureIQ — Tests: Coverage Analyzer Agent (Agent 3)
Run with: pytest tests/test_coverage_analyzer.py -v

Gemini is mocked so these run without a real API key — safe for CI.
"""

import pytest
from unittest.mock import patch, MagicMock

from agents.coverage_analyzer_agent import (
    run_coverage_analyzer_agent,
    _build_coverage_prompt,
    _normalize_coverage_map,
    EXPECTED_LIST_FIELDS,
)


INGESTION_RESULT = {
    "status": "success",
    "document_type": "health",
    "sections": {
        "coverage_terms": "Hospitalization expenses covered up to sum insured.",
        "exclusions": "Pre-existing diseases excluded for first 2 years.",
        "definitions": "Network Hospital means a hospital in the insurer panel.",
        "premium_schedule": "Annual premium Rs.15,000.",
    },
    "raw_text": "Health insurance policy. Hospitalization covered.",
}

MOCK_GEMINI_RESPONSE = """{
  "covered_events": [
    {"event": "Hospitalization", "conditions": "Up to sum insured"}
  ],
  "excluded_events": [
    {"event": "Pre-existing diseases", "reason": "First 2 years"}
  ],
  "waiting_periods": [
    {"condition": "Pre-existing diseases", "duration": "24 months"}
  ],
  "sub_limits": [
    {"category": "Room rent", "limit": "1% of sum insured per day"}
  ],
  "coverage_summary": "Covers hospitalization with a 2-year wait on pre-existing conditions."
}"""


def _mock_model(response_text):
    model = MagicMock()
    model.generate_content.return_value.text = response_text
    return model


class TestBuildCoveragePrompt:
    def test_includes_coverage_and_exclusion_sections(self):
        prompt = _build_coverage_prompt(INGESTION_RESULT)
        assert "COVERAGE_TERMS" in prompt
        assert "EXCLUSIONS" in prompt
        assert "health insurance" in prompt

    def test_excludes_irrelevant_sections(self):
        # premium_schedule is not part of coverage analysis.
        prompt = _build_coverage_prompt(INGESTION_RESULT)
        assert "PREMIUM_SCHEDULE" not in prompt

    def test_falls_back_to_raw_text(self):
        result = {"document_type": "car", "sections": {}, "raw_text": "Raw fallback"}
        prompt = _build_coverage_prompt(result)
        assert "Raw fallback" in prompt


class TestNormalizeCoverageMap:
    def test_missing_fields_default_to_empty(self):
        normalized = _normalize_coverage_map({})
        for field in EXPECTED_LIST_FIELDS:
            assert normalized[field] == []
        assert normalized["coverage_summary"] == ""

    def test_scalar_list_field_is_wrapped(self):
        normalized = _normalize_coverage_map({"covered_events": {"event": "x"}})
        assert normalized["covered_events"] == [{"event": "x"}]


class TestRunCoverageAnalyzerAgent:
    @patch("agents.coverage_analyzer_agent.genai")
    def test_successful_analysis(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model(MOCK_GEMINI_RESPONSE)
        mock_genai.configure = MagicMock()

        result = run_coverage_analyzer_agent(INGESTION_RESULT)

        assert result["status"] == "success"
        assert len(result["covered_events"]) == 1
        assert len(result["excluded_events"]) == 1
        assert result["waiting_periods"][0]["duration"] == "24 months"
        assert "hospitalization" in result["coverage_summary"].lower()

    @patch("agents.coverage_analyzer_agent.genai")
    def test_all_keys_present_on_empty_response(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model("{}")
        mock_genai.configure = MagicMock()

        result = run_coverage_analyzer_agent(INGESTION_RESULT)

        for field in EXPECTED_LIST_FIELDS:
            assert result[field] == []
        assert result["coverage_summary"] == ""

    @patch("agents.coverage_analyzer_agent.genai")
    def test_invalid_json_raises(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model("garbage")
        mock_genai.configure = MagicMock()

        with pytest.raises(ValueError, match="invalid JSON"):
            run_coverage_analyzer_agent(INGESTION_RESULT)
