"""
InsureIQ — End-to-End Smoke Test
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Runs the full real pipeline — Agent 1 (Ingestion) → Agent 2 (Policy Extractor)
→ Agent 3 (Coverage Analyzer) → Agent 4 (Financial Evaluator) → Agent 5 (Risk Flag)
→ Agent 6 (Report Composer) — against a real document using the real Gemini API,
prints each agent's output, and writes the final .docx report to output/.

Unlike the pytest suite (which mocks Gemini), this makes actual API calls, so it
needs a valid GEMINI_API_KEY in your .env. Use it to sanity-check extraction quality
on real documents.

Usage:
    python scripts/smoke_test.py                       # uses the bundled sample doc
    python scripts/smoke_test.py path/to/policy.pdf    # your own document
"""

import io
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Make the project importable no matter where this script is invoked from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Force UTF-8 stdout so currency symbols (₹, €, £) print on Windows' cp1252 console.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from agents.ingestion_agent import run_ingestion_agent
from agents.policy_extractor_agent import run_policy_extractor_agent
from agents.coverage_analyzer_agent import run_coverage_analyzer_agent
from agents.financial_evaluator_agent import run_financial_evaluator_agent
from agents.risk_flag_agent import run_risk_flag_agent
from agents.report_composer_agent import run_report_composer_agent
from agents.gemini_utils import GeminiQuotaExhaustedError
from config.settings import settings

DEFAULT_DOC = PROJECT_ROOT / "sample_docs" / "sample_life_insurance_policy.docx"
OUTPUT_DIR = PROJECT_ROOT / "output"


def _dump(label: str, data: dict) -> None:
    print(f"\n{'─' * 70}\n{label}\n{'─' * 70}")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main() -> None:
    settings.validate()  # fail fast with a clear message if GEMINI_API_KEY is missing

    doc_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DOC
    if not doc_path.exists():
        sys.exit(f"Document not found: {doc_path}")

    file_bytes = doc_path.read_bytes()
    print(f"\n=== InsureIQ smoke test — {doc_path.name} ({len(file_bytes)} bytes) ===")

    # ── Agent 1: Ingestion ────────────────────────────────────────────────────
    ingestion = run_ingestion_agent(file_bytes, doc_path.name)
    print(f"\n[Agent 1] document_type={ingestion['document_type']} "
          f"extraction={ingestion['extraction_method']} "
          f"sections_found={[k for k, v in ingestion['sections'].items() if v]}")

    # ── Agent 2: Policy Extractor ─────────────────────────────────────────────
    policy = run_policy_extractor_agent(ingestion)
    _dump("[Agent 2] Policy Data", policy)

    # ── Agent 3: Coverage Analyzer ────────────────────────────────────────────
    coverage = run_coverage_analyzer_agent(ingestion)
    _dump("[Agent 3] Coverage Map", coverage)

    # ── Agent 4: Financial Evaluator ──────────────────────────────────────────
    financial = run_financial_evaluator_agent(policy, document_type=ingestion["document_type"])
    _dump("[Agent 4] Financial Verdict", financial)

    # ── Agent 5: Risk Flag ────────────────────────────────────────────────────
    risk = run_risk_flag_agent(ingestion)
    _dump("[Agent 5] Risk Flags", risk)

    # ── Agent 6: Report Composer ──────────────────────────────────────────────
    report = run_report_composer_agent(
        policy_data=policy,
        coverage_map=coverage,
        financial_verdict=financial,
        risk_flags=risk,
        document_type=ingestion["document_type"],
    )
    _dump("[Agent 6] Report Intros", report["report_intros"])

    # Write the final .docx so you can open and eyeball the formatted report.
    OUTPUT_DIR.mkdir(exist_ok=True)
    report_path = OUTPUT_DIR / f"{doc_path.stem}_insureiq_report.docx"
    try:
        report_path.write_bytes(report["report_bytes"])
    except PermissionError:
        # The target is almost certainly open in Word (Windows locks open files).
        # Fall back to a timestamped name so the run still produces an artifact.
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = OUTPUT_DIR / f"{doc_path.stem}_insureiq_report_{stamp}.docx"
        print(f"\n[Agent 6] Default report file is locked (open in Word?) — writing to a new file instead.")
        report_path.write_bytes(report["report_bytes"])
    print(f"\n[Agent 6] Report written to: {report_path} ({len(report['report_bytes'])} bytes)")

    # ── Contract checks downstream agents rely on ─────────────────────────────
    assert policy["status"] == "success", "Agent 2 did not return success"
    assert coverage["status"] == "success", "Agent 3 did not return success"
    assert financial["status"] == "success", "Agent 4 did not return success"
    assert risk["status"] == "success", "Agent 5 did not return success"
    assert report["status"] == "success", "Agent 6 did not return success"
    assert "maturity_date" in policy, "normalization should guarantee this key"
    assert isinstance(coverage["covered_events"], list), "covered_events must be a list"
    assert "verdict" in financial, "Agent 4 must always return a verdict"
    assert isinstance(risk["flags"], list), "risk flags must be a list"
    assert isinstance(report["report_bytes"], bytes) and report["report_bytes"], "Agent 6 must return .docx bytes"
    assert report_path.exists(), "report .docx was not written"

    print("\n✅ Smoke test passed — all six agents returned valid output; report saved.\n")


if __name__ == "__main__":
    try:
        main()
    except GeminiQuotaExhaustedError as e:
        # Expected on a used-up free-tier key — exit cleanly with a clear message
        # instead of dumping a traceback that looks like a crash.
        print(f"\n⚠️  {e}\n")
        sys.exit(2)
