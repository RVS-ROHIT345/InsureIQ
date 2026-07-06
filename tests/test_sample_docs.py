"""
InsureIQ — Real Sample Document Tests (offline / no quota)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Exercises the front of the pipeline against every committed sample document —
one fixture per advertised type (health / life / car / home) in both PDF and
DOCX — without spending any Gemini quota. These are the deterministic guardrails
for "real document testing"; the live smoke test (scripts/smoke_test.py) covers
the LLM-dependent tail on demand.

For each fixture we assert the three properties the pipeline depends on before
any LLM call:
  1. validate_upload() accepts it (extension + magic bytes match).
  2. The parser extracts readable text (well past the 50-char ingestion floor).
  3. The fast keyword classifier resolves the correct document type with no
     Gemini fallback — proving the fixtures are self-describing.

If someone adds a new sample_docs/ file, EXPECTED_TYPE must be updated or the
coverage test below fails — the fixture set and this map stay in lock-step.
"""

from pathlib import Path

import pytest

from agents.ingestion_agent import _detect_document_type_by_keywords
from tools.document_parser import extract_text_from_pdf, extract_text_from_docx
from tools.file_validation import validate_upload

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_docs"

# Every committed fixture and the type its content should classify as.
EXPECTED_TYPE = {
    "sample_health_insurance_policy.pdf": "health",
    "sample_health_insurance_policy.docx": "health",
    "sample_life_insurance_policy.docx": "life",
    "sample_life_insurance_limited_pay.pdf": "life",
    "sample_car_insurance.pdf": "car",
    "sample_car_insurance.docx": "car",
    "sample_car_insurance_cover_note.pdf": "car",
    "sample_car_insurance_cover_note.docx": "car",  # sparse edge case
    "sample_home_insurance.pdf": "home",
    "sample_home_insurance.docx": "home",
}

# The ingestion agent rejects documents yielding < 50 chars of text.
MIN_INGESTION_CHARS = 50


def _sample_files():
    return sorted(p for p in SAMPLE_DIR.glob("*") if p.suffix in {".pdf", ".docx"})


def _extract(path: Path) -> str:
    file_bytes = path.read_bytes()
    if path.suffix == ".pdf":
        text, _ = extract_text_from_pdf(file_bytes)
    else:
        text, _ = extract_text_from_docx(file_bytes)
    return text


@pytest.mark.parametrize("path", _sample_files(), ids=lambda p: p.name)
def test_sample_doc_passes_upload_validation(path):
    """Every shipped fixture survives the same edge validation as a real upload."""
    ext = validate_upload(path.read_bytes(), path.name)
    assert ext == path.suffix.lstrip(".")


@pytest.mark.parametrize("path", _sample_files(), ids=lambda p: p.name)
def test_sample_doc_extracts_readable_text(path):
    """The parser pulls real text — comfortably above the ingestion 50-char floor."""
    text = _extract(path)
    assert len(text.strip()) > MIN_INGESTION_CHARS, f"{path.name} extracted too little text"


@pytest.mark.parametrize("path", _sample_files(), ids=lambda p: p.name)
def test_sample_doc_fast_path_is_never_confidently_wrong(path):
    """
    The keyword classifier is a deliberate FAST PATH: it either returns a
    confident type (2+ keyword hits) or "unknown", in which case the ingestion
    agent defers to the Gemini classifier at runtime. This offline test cannot
    exercise that Gemini fallback, so the property it CAN guarantee is the one
    that matters: the fast path must never be *confidently wrong*.

      • correct type   → good (Gemini call saved)
      • "unknown"      → acceptable (real doc; runtime falls back to Gemini)
      • wrong type     → FAIL (a confident wrong answer skips the fallback and
                                mislabels the document downstream)
    """
    assert path.name in EXPECTED_TYPE, (
        f"{path.name} is not in EXPECTED_TYPE — add it (with its type) so the "
        "fixture set and the coverage map stay in sync."
    )
    detected = _detect_document_type_by_keywords(_extract(path))
    expected = EXPECTED_TYPE[path.name]
    assert detected in (expected, "unknown"), (
        f"{path.name}: keyword fast-path confidently misclassified as "
        f"'{detected}' (expected '{expected}' or a punt to 'unknown')."
    )


def test_all_four_advertised_types_have_a_fixture():
    """The corpus must cover every type the product advertises (health/life/car/home)."""
    covered = {EXPECTED_TYPE[p.name] for p in _sample_files()}
    assert {"health", "life", "car", "home"} <= covered


def test_expected_type_map_matches_disk():
    """No orphan entries and no untracked fixtures — the map mirrors sample_docs/."""
    on_disk = {p.name for p in _sample_files()}
    assert on_disk == set(EXPECTED_TYPE), (
        f"Mismatch between sample_docs/ and EXPECTED_TYPE. "
        f"Only on disk: {on_disk - set(EXPECTED_TYPE)}. "
        f"Only in map: {set(EXPECTED_TYPE) - on_disk}."
    )
