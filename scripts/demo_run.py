"""
InsureIQ — Demo Runner (built for the submission video)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A screen-recording-friendly driver for the 2:30–4:00 "live demo" segment of the
submission video. It runs one real insurance document through all six agents,
narrating each hand-off on screen with a timing, then prints a clean AT-A-GLANCE
panel highlighting exactly what the rubric asks the demo to show:

    • the maturity date       (Agent 2 — Policy Extractor)
    • the financial verdict   (Agent 4 — Financial Evaluator)
    • the red flags           (Agent 5 — Risk Flag)

Unlike the pytest suite (which mocks Gemini), this makes REAL Gemini calls, so it
needs a valid GEMINI_API_KEY in your .env. It is the on-camera counterpart to
scripts/smoke_test.py — same pipeline, but formatted for a viewer rather than a
developer (no raw JSON dumps).

Usage:
    python scripts/demo_run.py                                   # bundled life policy (PDF)
    python scripts/demo_run.py sample_docs/sample_home_insurance.pdf
    python scripts/demo_run.py path/to/your/policy.pdf --no-color
"""

import io
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

# Keep the on-camera output clean — silence third-party import warnings
# (e.g. google-cloud-aiplatform's storage FutureWarning) that would otherwise
# print above the demo banner.
warnings.filterwarnings("ignore")

# Make the project importable no matter where this script is invoked from.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Force UTF-8 stdout so currency symbols (₹, €, £) and box-drawing print on
# Windows' cp1252 console (and inside OBS/Loom captures of that console).
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# NOTE: no basicConfig here on purpose — the pipeline's INFO logs are muted so the
# on-screen narration below is clean. smoke_test.py is the verbose counterpart.

from agents.ingestion_agent import run_ingestion_agent
from agents.policy_extractor_agent import run_policy_extractor_agent
from agents.coverage_analyzer_agent import run_coverage_analyzer_agent
from agents.financial_evaluator_agent import run_financial_evaluator_agent
from agents.risk_flag_agent import run_risk_flag_agent
from agents.report_composer_agent import run_report_composer_agent
from agents.gemini_utils import GeminiQuotaExhaustedError
from config.settings import settings

# The default doc is a limited-pay LIFE policy: it exercises every headline the
# demo needs on camera — a maturity date, a full IRR/benchmark financial verdict,
# and a spread of red flags. Term/health policies (no maturity) make a duller demo.
DEFAULT_DOC = PROJECT_ROOT / "sample_docs" / "sample_life_insurance_limited_pay.pdf"
OUTPUT_DIR = PROJECT_ROOT / "output"

WIDTH = 74
_USE_COLOR = True  # toggled off by --no-color or a non-tty


def _c(code: str, text: str) -> str:
    """Wrap text in an ANSI colour unless colour is disabled."""
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(t):   return _c("1", t)
def dim(t):    return _c("2", t)
def green(t):  return _c("32", t)
def yellow(t): return _c("33", t)
def red(t):    return _c("31", t)
def cyan(t):   return _c("36", t)


def rule(char: str = "─") -> None:
    print(char * WIDTH)


def banner(title: str) -> None:
    print()
    print(cyan("╔" + "═" * (WIDTH - 2) + "╗"))
    print(cyan("║") + bold(title.center(WIDTH - 2)) + cyan("║"))
    print(cyan("╚" + "═" * (WIDTH - 2) + "╝"))


def step(n: int, name: str, role: str) -> None:
    print()
    print(f"{cyan(f'▶ Agent {n}')} {bold(name)} {dim('— ' + role)}")


def done(elapsed: float, *facts: str) -> None:
    print(f"  {green('✓')} {dim(f'{elapsed:4.1f}s')}  " + "   ".join(facts))


def val(x) -> str:
    """Render a possibly-missing field for display."""
    if x is None or x == "" or x == []:
        return dim("not specified")
    return str(x)


def main() -> None:
    global _USE_COLOR
    args = [a for a in sys.argv[1:] if a != "--no-color"]
    if "--no-color" in sys.argv[1:] or not sys.stdout.isatty():
        _USE_COLOR = False

    settings.validate()  # fail fast with a clear message if GEMINI_API_KEY is missing

    doc_path = Path(args[0]) if args else DEFAULT_DOC
    if not doc_path.exists():
        sys.exit(f"Document not found: {doc_path}")

    file_bytes = doc_path.read_bytes()

    banner("InsureIQ  ·  6-Agent Insurance Policy Analyst")
    print(f"  {dim('Document :')} {bold(doc_path.name)}  {dim(f'({len(file_bytes):,} bytes)')}")
    print(f"  {dim('Pipeline :')} Ingestion → Policy → Coverage → Financial → Risk → Report")
    rule()

    t0 = time.time()

    # ── Agent 1: Ingestion ────────────────────────────────────────────────────
    step(1, "Ingestion", "read & classify the document")
    s = time.time()
    ingestion = run_ingestion_agent(file_bytes, doc_path.name)
    found = [k for k, v in ingestion["sections"].items() if v]
    done(time.time() - s,
         f"type={bold(ingestion['document_type'])}",
         f"via {ingestion['extraction_method']}",
         f"{len(found)} sections")

    # ── Agent 2: Policy Extractor ─────────────────────────────────────────────
    step(2, "Policy Extractor", "pull the structured facts")
    s = time.time()
    policy = run_policy_extractor_agent(ingestion)
    done(time.time() - s,
         f"insurer={val(policy.get('insurer_name'))}",
         f"maturity={bold(val(policy.get('maturity_date')))}")

    # ── Agent 3: Coverage Analyzer ────────────────────────────────────────────
    step(3, "Coverage Analyzer", "what's covered vs excluded")
    s = time.time()
    coverage = run_coverage_analyzer_agent(ingestion)
    done(time.time() - s,
         f"{len(coverage['covered_events'])} covered",
         f"{len(coverage['excluded_events'])} excluded",
         f"{len(coverage['waiting_periods'])} waiting periods")

    # ── Agent 4: Financial Evaluator ──────────────────────────────────────────
    step(4, "Financial Evaluator", "is it worth the money?")
    s = time.time()
    financial = run_financial_evaluator_agent(policy, document_type=ingestion["document_type"])
    irr = financial.get("effective_annual_return_pct")
    done(time.time() - s,
         f"verdict={bold(val(financial.get('verdict')))}",
         f"IRR={val(irr)}%" if irr is not None else dim("no maturity → protection-only"))

    # ── Agent 5: Risk Flag ────────────────────────────────────────────────────
    step(5, "Risk Flag", "surface the fine-print traps")
    s = time.time()
    risk = run_risk_flag_agent(ingestion)
    done(time.time() - s,
         f"overall={bold(val(risk.get('overall_risk_level')))}",
         f"{red(str(risk.get('total_high', 0)) + ' HIGH')}",
         f"{yellow(str(risk.get('total_medium', 0)) + ' MED')}",
         f"{risk.get('total_low', 0)} LOW")

    # ── Agent 6: Report Composer ──────────────────────────────────────────────
    step(6, "Report Composer", "assemble the plain-English .docx")
    s = time.time()
    report = run_report_composer_agent(
        policy_data=policy,
        coverage_map=coverage,
        financial_verdict=financial,
        risk_flags=risk,
        document_type=ingestion["document_type"],
    )
    OUTPUT_DIR.mkdir(exist_ok=True)
    report_path = OUTPUT_DIR / f"{doc_path.stem}_insureiq_report.docx"
    try:
        report_path.write_bytes(report["report_bytes"])
    except PermissionError:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = OUTPUT_DIR / f"{doc_path.stem}_insureiq_report_{stamp}.docx"
        report_path.write_bytes(report["report_bytes"])
    done(time.time() - s, f"{len(report['report_bytes']):,}-byte .docx written")

    total = time.time() - t0

    # ── AT-A-GLANCE — the three things the rubric wants shown on camera ────────
    banner("AT A GLANCE")
    print(f"  {dim('Document type ')} {bold(ingestion['document_type'].upper())}")
    print()
    print(f"  {cyan('MATURITY DATE')}   {bold(val(policy.get('maturity_date')))}"
          f"   {dim('(sum assured ' + val(policy.get('sum_assured')) + ')')}")
    print()

    verdict = str(financial.get("verdict") or "—")
    v_color = green if "PROFIT" in verdict else (red if "LOSS" in verdict else yellow)
    print(f"  {cyan('FINANCIAL VERDICT')}   {v_color(bold(verdict))}")
    if financial.get("effective_annual_return_pct") is not None:
        print(f"     {dim('effective return ')} {financial['effective_annual_return_pct']}%"
              f"   {dim('vs FD ')} {val(financial.get('fd_benchmark_pct'))}%"
              f"   {dim('vs index ')} {val(financial.get('index_fund_benchmark_pct'))}%")
    if financial.get("verdict_plain_english"):
        print(f"     {dim(financial['verdict_plain_english'])}")
    print()

    print(f"  {cyan('RED FLAGS')}   overall risk "
          f"{v_flag(risk.get('overall_risk_level'))}"
          f"   {red(str(risk.get('total_high', 0)) + ' high')} /"
          f" {yellow(str(risk.get('total_medium', 0)) + ' med')} /"
          f" {risk.get('total_low', 0)} low")
    for flag in risk.get("flags", [])[:3]:
        sev = flag["severity"]
        tag = red(sev) if sev == "HIGH" else (yellow(sev) if sev == "MEDIUM" else dim(sev))
        print(f"     • [{tag}] {flag['category']}: {flag['description'][:70]}")

    rule()
    print(f"  {green('✓')} Full 6-agent pipeline finished in {bold(f'{total:.1f}s')}")
    print(f"  {green('✓')} Plain-English report: {bold(str(report_path))}")
    print()


def v_flag(level) -> str:
    level = str(level or "—")
    if level == "HIGH":
        return red(bold(level))
    if level == "MEDIUM":
        return yellow(bold(level))
    return green(bold(level)) if level in ("LOW", "NONE") else level


if __name__ == "__main__":
    try:
        main()
    except GeminiQuotaExhaustedError as e:
        # Expected on a used-up free-tier key — exit cleanly with a clear message
        # instead of a traceback that looks like a crash on camera.
        print(f"\n⚠️  {e}\n")
        sys.exit(2)
