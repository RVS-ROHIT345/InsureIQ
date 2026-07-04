"""
InsureIQ — Shared Gemini Utilities
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Helpers reused by every LLM-backed agent in the pipeline:
  - call_gemini_with_retry: robust API call with exponential backoff
  - parse_gemini_json_response: safely parse JSON (strips markdown fences)

Keeping these in one place means all agents share identical retry and
JSON-hardening behaviour — tune it once, every agent benefits.
"""

import json
import logging
import time

logger = logging.getLogger(__name__)

# Max retries for Gemini API calls with exponential backoff.
# Insurance docs are large — occasionally hit rate limits on the first call.
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2  # seconds


def call_gemini_with_retry(model, prompt: str, system_prompt: str = "") -> str:
    """
    Call the Gemini API with exponential backoff retry logic.

    Args:
        model: Configured Gemini GenerativeModel instance
        prompt: User prompt text
        system_prompt: Optional extra system instruction prepended to the call

    Returns:
        Gemini response text

    Raises:
        RuntimeError: If all retries are exhausted
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = model.generate_content(
                [system_prompt, prompt] if system_prompt else [prompt],
                generation_config={"temperature": 0.1},  # Low temp for structured extraction
            )
            return response.text

        except Exception as e:
            if attempt == MAX_RETRIES:
                raise RuntimeError(
                    f"Gemini API failed after {MAX_RETRIES} attempts: {e}"
                ) from e

            wait = RETRY_BASE_DELAY ** attempt
            logger.warning(
                f"Gemini call failed (attempt {attempt}/{MAX_RETRIES}): {e}. Retrying in {wait}s..."
            )
            time.sleep(wait)


def parse_gemini_json_response(raw_response: str) -> dict:
    """
    Safely parse Gemini's JSON output.
    Gemini occasionally wraps JSON in ```json ... ``` fences — strip them.

    Args:
        raw_response: Raw text from Gemini

    Returns:
        Parsed dict

    Raises:
        ValueError: If the response cannot be parsed as JSON
    """
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # Remove first line (```json or ```) and, if present, the trailing ```
        cleaned = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Gemini returned invalid JSON. Raw response (first 500 chars): "
            f"{raw_response[:500]}... Error: {e}"
        ) from e
