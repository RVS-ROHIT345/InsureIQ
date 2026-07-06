"""
InsureIQ — Pipeline Orchestrator
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Runs the full 6-agent chain in sequence. Each agent receives the structured
output of the previous agent — this is a genuine dependency chain, not parallel
calls with a wrapper.

Agent execution order:
  1. IngestionAgent      → IngestionResult
  2. PolicyExtractorAgent → PolicyData
  3. CoverageAnalyzerAgent → CoverageMap
  4. FinancialEvaluatorAgent → FinancialVerdict
  5. RiskFlagAgent       → RiskFlags
  6. ReportComposerAgent → Final .docx bytes

Kaggle concepts demonstrated:
  - Multi-agent system (ADK) — 6 agents with explicit sequential handoffs
  - Agent Skills — financial_calculator.py registered as ADK tool in Agent 4
"""

import logging
import time
from typing import Optional

from agents.ingestion_agent import run_ingestion_agent
from agents.policy_extractor_agent import run_policy_extractor_agent
from agents.coverage_analyzer_agent import run_coverage_analyzer_agent
from agents.financial_evaluator_agent import run_financial_evaluator_agent
from agents.risk_flag_agent import run_risk_flag_agent
from agents.report_composer_agent import run_report_composer_agent

logger = logging.getLogger(__name__)


def run_pipeline(file_bytes: bytes, filename: str) -> dict:
    """
    Execute the full InsureIQ 6-agent pipeline.

    Args:
        file_bytes: Raw uploaded file bytes (in memory — never written to disk)
        filename: Original filename

    Returns:
        PipelineResult dict with:
          - report_bytes: Final .docx report as bytes
          - policy_data: Structured policy info (Agent 2 output)
          - financial_verdict: ROI analysis (Agent 4 output)
          - risk_flags: Ordered risk list (Agent 5 output)
          - metadata: Timing and method info

    Raises:
        ValueError: On unreadable or invalid documents
        RuntimeError: On agent failures
    """
    pipeline_start = time.time()
    logger.info(f"Pipeline starting — file: {filename}")

    results = {}

    # ── Agent 1: Ingestion ────────────────────────────────────────────────────
    logger.info("▶ Agent 1: Ingestion")
    agent1_start = time.time()
    ingestion_result = run_ingestion_agent(file_bytes, filename)
    results["ingestion"] = ingestion_result
    logger.info(f"✓ Agent 1 complete ({time.time() - agent1_start:.1f}s) — type: {ingestion_result['document_type']}")

    # ── Agent 2: Policy Extractor ─────────────────────────────────────────────
    logger.info("▶ Agent 2: Policy Extractor")
    agent2_start = time.time()
    policy_data = run_policy_extractor_agent(ingestion_result)
    results["policy_data"] = policy_data
    logger.info(f"✓ Agent 2 complete ({time.time() - agent2_start:.1f}s)")

    # ── Agent 3: Coverage Analyzer ────────────────────────────────────────────
    logger.info("▶ Agent 3: Coverage Analyzer")
    agent3_start = time.time()
    coverage_map = run_coverage_analyzer_agent(ingestion_result)
    results["coverage_map"] = coverage_map
    logger.info(f"✓ Agent 3 complete ({time.time() - agent3_start:.1f}s)")

    # ── Agent 4: Financial Evaluator ──────────────────────────────────────────
    logger.info("▶ Agent 4: Financial Evaluator")
    agent4_start = time.time()
    financial_verdict = run_financial_evaluator_agent(
        policy_data, document_type=ingestion_result.get("document_type", "unknown")
    )
    results["financial_verdict"] = financial_verdict
    logger.info(f"✓ Agent 4 complete ({time.time() - agent4_start:.1f}s) — verdict: {financial_verdict.get('verdict')}")

    # ── Agent 5: Risk Flag ────────────────────────────────────────────────────
    logger.info("▶ Agent 5: Risk Flag")
    agent5_start = time.time()
    risk_flags = run_risk_flag_agent(ingestion_result)
    results["risk_flags"] = risk_flags
    logger.info(f"✓ Agent 5 complete ({time.time() - agent5_start:.1f}s) — overall risk: {risk_flags.get('overall_risk_level')}")

    # ── Agent 6: Report Composer ──────────────────────────────────────────────
    logger.info("▶ Agent 6: Report Composer")
    agent6_start = time.time()
    report_result = run_report_composer_agent(
        policy_data=policy_data,
        coverage_map=coverage_map,
        financial_verdict=financial_verdict,
        risk_flags=risk_flags,
        document_type=ingestion_result.get("document_type", "unknown"),
    )
    report_bytes = report_result["report_bytes"]
    results["report_intros"] = report_result["report_intros"]
    results["report_bytes"] = report_bytes
    logger.info(
        f"✓ Agent 6 complete ({time.time() - agent6_start:.1f}s) — "
        f"report {len(report_bytes)} bytes"
    )

    pipeline_duration = time.time() - pipeline_start
    logger.info(f"Pipeline complete in {pipeline_duration:.1f}s")

    return {
        **results,
        "metadata": {
            "filename": filename,
            "document_type": ingestion_result.get("document_type"),
            "extraction_method": ingestion_result.get("extraction_method"),
            "pipeline_duration_seconds": round(pipeline_duration, 2),
        }
    }
