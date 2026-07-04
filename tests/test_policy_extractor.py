"""
InsureIQ — Tests: Policy Extractor Agent (Agent 2)
Run with: pytest tests/test_policy_extractor.py -v

Gemini is mocked so these run without a real API key — safe for CI.
"""

import pytest
from unittest.mock import patch, MagicMock

from agents.policy_extractor_agent import (
    run_policy_extractor_agent,
    _build_extraction_prompt,
    _normalize_policy_data,
    EXPECTED_STRING_FIELDS,
    EXPECTED_LIST_FIELDS,
)


# A representative ingestion result handed to Agent 2 by Agent 1.
INGESTION_RESULT = {
    "status": "success",
    "document_type": "life",
    "sections": {
        "definitions": "Sum Assured means the guaranteed amount payable.",
        "coverage_terms": "Death benefit payable upon death of life assured.",
        "exclusions": "Suicide within the first policy year is excluded.",
        "premium_schedule": "Annual premium of Rs.12,000 due on 1st January.",
        "maturity_clause": "Maturity benefit of Rs.5,00,000 payable on 2044-01-01.",
        "terms_and_conditions": "Policy lapses if premium not paid within 30 days grace.",
    },
    "raw_text": "LIC Life Insurance Policy. Sum Assured Rs.5,00,000.",
}

MOCK_GEMINI_RESPONSE = """```json
{
  "policy_number": "LIC-12345",
  "insurer_name": "Life Insurance Corporation",
  "policyholder_name": "Rohit Sharma",
  "policy_start_date": "2024-01-01",
  "policy_end_date": "2044-01-01",
  "policy_term_years": 20,
  "sum_assured": "Rs.5,00,000",
  "premium_amount": "Rs.12,000",
  "premium_frequency": "annual",
  "premium_due_dates": ["2024-01-01", "2025-01-01"],
  "grace_period_days": 30,
  "maturity_date": "2044-01-01",
  "maturity_benefit": "Rs.5,00,000",
  "free_look_period_days": 15,
  "nominee_name": "Priya Sharma",
  "lapse_conditions": ["Premium not paid within grace period"],
  "loan_against_policy": "yes"
}
```"""


def _mock_model(response_text):
    model = MagicMock()
    model.generate_content.return_value.text = response_text
    return model


class TestBuildExtractionPrompt:
    def test_includes_relevant_sections(self):
        prompt = _build_extraction_prompt(INGESTION_RESULT)
        assert "PREMIUM_SCHEDULE" in prompt
        assert "MATURITY_CLAUSE" in prompt
        assert "life insurance" in prompt

    def test_falls_back_to_raw_text_when_no_sections(self):
        result = {"document_type": "life", "sections": {}, "raw_text": "Fallback body text"}
        prompt = _build_extraction_prompt(result)
        assert "Fallback body text" in prompt

    def test_handles_completely_empty_input(self):
        prompt = _build_extraction_prompt({})
        assert "no document content available" in prompt

    def test_includes_document_header_for_identity_fields(self):
        # Policy number / insurer / nominee live in the schedule at the top of the
        # doc, not in any labeled section. The header block must carry them through.
        result = {
            "document_type": "life",
            "sections": {"coverage_terms": "Death benefit payable."},
            "raw_text": "Policy Number | SLA/2025/0193847\nInsurer: SecureLife\nNominee | Rajesh",
        }
        prompt = _build_extraction_prompt(result)
        assert "DOCUMENT HEADER" in prompt
        assert "SLA/2025/0193847" in prompt
        assert "Rajesh" in prompt


class TestNormalizePolicyData:
    def test_missing_fields_default_to_none_and_empty_list(self):
        normalized = _normalize_policy_data({})
        for field in EXPECTED_STRING_FIELDS:
            assert normalized[field] is None
        for field in EXPECTED_LIST_FIELDS:
            assert normalized[field] == []

    def test_scalar_list_field_is_wrapped(self):
        normalized = _normalize_policy_data({"lapse_conditions": "single condition"})
        assert normalized["lapse_conditions"] == ["single condition"]

    def test_preserves_provided_values(self):
        normalized = _normalize_policy_data({"policy_number": "ABC-1", "premium_due_dates": ["a"]})
        assert normalized["policy_number"] == "ABC-1"
        assert normalized["premium_due_dates"] == ["a"]


class TestRunPolicyExtractorAgent:
    @patch("agents.policy_extractor_agent.genai")
    def test_successful_extraction(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model(MOCK_GEMINI_RESPONSE)
        mock_genai.configure = MagicMock()

        result = run_policy_extractor_agent(INGESTION_RESULT)

        assert result["status"] == "success"
        assert result["policy_number"] == "LIC-12345"
        assert result["maturity_date"] == "2044-01-01"
        assert result["grace_period_days"] == 30
        assert result["premium_due_dates"] == ["2024-01-01", "2025-01-01"]

    @patch("agents.policy_extractor_agent.genai")
    def test_all_expected_keys_present_on_partial_response(self, mock_genai):
        # Gemini returns only two fields — the rest must still be present.
        mock_genai.GenerativeModel.return_value = _mock_model('{"policy_number": "X-1"}')
        mock_genai.configure = MagicMock()

        result = run_policy_extractor_agent(INGESTION_RESULT)

        for field in EXPECTED_STRING_FIELDS + EXPECTED_LIST_FIELDS:
            assert field in result
        assert result["policy_number"] == "X-1"
        assert result["nominee_name"] is None

    @patch("agents.policy_extractor_agent.genai")
    def test_invalid_json_raises(self, mock_genai):
        mock_genai.GenerativeModel.return_value = _mock_model("not json at all")
        mock_genai.configure = MagicMock()

        with pytest.raises(ValueError, match="invalid JSON"):
            run_policy_extractor_agent(INGESTION_RESULT)
