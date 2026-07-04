# InsureIQ — Build Progress Log

Track: Concierge Agents
Deadline: July 6, 2026 at 11:59 PM PT
GitHub: [to be added]
Live URL: [to be added after Day 7]

---

## Testing convention (standing rule, Days 3–10)

**Mocked-first, test sparingly.** The pytest suite mocks Gemini — it is free, instant,
and covers all agent logic. Run it freely after every change:

    pytest tests/ -q

The live smoke test (`python scripts/smoke_test.py`) makes real Gemini calls (~3 per run)
and counts against the daily free-tier quota. Run it **sparingly** — once after a meaningful
change to an agent's real behaviour, on a single document, never in loops. The user runs it
manually in their own terminal; the assistant does **not** run it (to conserve quota and let
the user see full output). Add mocked unit tests for new agents; reserve live runs for
real-document sanity checks only.

---

## Day 1 — Project Setup + MCP File Server + Ingestion Agent ✅

**Completed:**
- [x] Full folder structure scaffolded
- [x] requirements.txt with pinned dependencies
- [x] .env.example with placeholder values
- [x] .gitignore (includes .env, uploads/, output/)
- [x] config/settings.py — centralized config from env vars
- [x] config/agent_prompts.py — all 6 agent system prompts
- [x] tools/document_parser.py — pdfplumber + python-docx + Gemini vision fallback
- [x] tools/financial_calculator.py — stub (full implementation Day 3)
- [x] tools/report_generator.py — stub (full implementation Day 4)
- [x] mcp/file_server.py — MCP server with upload + validate tools, magic bytes check
- [x] agents/ingestion_agent.py — full Agent 1 implementation
- [x] agents/policy_extractor_agent.py — stub
- [x] agents/coverage_analyzer_agent.py — stub
- [x] agents/financial_evaluator_agent.py — stub
- [x] agents/risk_flag_agent.py — stub
- [x] agents/report_composer_agent.py — stub
- [x] pipeline.py — orchestrator skeleton (Agents 2-6 stubbed)
- [x] main.py — FastAPI with POST /analyze, GET /health
- [x] tests/test_ingestion.py — 10 tests covering parser, MCP, agent
- [x] README.md — initial version

**Key decisions:**
- Gemini vision fallback in document_parser.py handles scanned insurance PDFs without any OCR library
- Magic bytes validation in MCP server prevents disguised file uploads
- Document type detection runs keyword scoring first (fast/free), falls back to Gemini only if inconclusive
- All agent system prompts in agent_prompts.py — tuning prompts doesn't require touching agent logic

**Next session (Day 2):** Policy Extractor Agent + Coverage Analyzer Agent

---

## Day 2 — Policy Extractor + Coverage Analyzer ✅

**Completed:**
- [x] agents/gemini_utils.py — shared `call_gemini_with_retry` + `parse_gemini_json_response`
      (extracted from ingestion_agent so all LLM agents share one retry/JSON-hardening path)
- [x] agents/ingestion_agent.py — refactored to use shared gemini_utils (no behaviour change)
- [x] agents/policy_extractor_agent.py — full Agent 2 implementation + ADK agent factory
- [x] agents/coverage_analyzer_agent.py — full Agent 3 implementation + ADK agent factory
- [x] pipeline.py — Agents 2 & 3 wired in with real calls + per-agent timing
- [x] tests/test_policy_extractor.py — 9 tests (prompt build, normalization, extraction, error paths)
- [x] tests/test_coverage_analyzer.py — 8 tests (prompt build, normalization, analysis, error paths)
- [x] Fixed broken import in tests/test_ingestion.py (`_validate_magic_bytes` lives in the file server)
- [x] Renamed local `mcp/` package → `mcp_server/` to stop it shadowing the installed `mcp` SDK
      (updated tests, docker-compose.yml, README) — full test suite now collects cleanly

**Key decisions:**
- Both agents consume relevant ingestion sections only (Policy Extractor: premium/maturity/T&C;
  Coverage Analyzer: coverage/exclusions/definitions) — keeps prompts focused and cheap.
- Fallback to raw_text when the ingestion agent finds no labeled sections — poorly-structured
  documents still get a best-effort extraction.
- Output normalization guarantees every promised schema field exists (missing → null / []),
  so downstream agents (4, 6) never KeyError on partial Gemini output.

**Next session (Day 3):** Financial Evaluator Agent (+ financial_calculator.py) + Risk Flag Agent

---

## Day 3 — Financial Evaluator + Risk Flag agents ✅

**Completed:**
- [x] tools/financial_calculator.py — finalized (dropped Day-1 stub language) + added
      deterministic parsing helpers: `parse_currency_to_float` (handles ₹/$/Rs./INR,
      Indian grouping "5,00,000", and "10 Lakhs" / "1.5 Crore" magnitude words),
      `detect_currency_symbol`, `parse_term_years`. `calculate_total_premium` now
      also handles single-premium policies.
- [x] agents/financial_evaluator_agent.py — full Agent 4 + ADK agent factory.
      Numbers computed deterministically by the calculator; Gemini writes ONLY the
      plain-English narrative (never invents figures). Graceful non-LLM branches for
      INSUFFICIENT_DATA and NO_MATURITY_BENEFIT (pure term/health cover).
- [x] agents/risk_flag_agent.py — full Agent 5 + ADK agent factory. Scans the whole
      document; severity tallies + overall_risk_level are recomputed from the flags
      list (Gemini's own counts are ignored so summary can't disagree with the flags).
- [x] pipeline.py — Agents 4 & 5 wired in with real calls + per-agent timing
- [x] tests/test_financial_calculator.py — 30 pure-arithmetic tests (no mocks/API)
- [x] tests/test_financial_evaluator.py — 8 tests (mocked Gemini; insufficient-data
      and no-maturity paths assert Gemini is NOT called)
- [x] tests/test_risk_flag.py — 12 tests (mocked Gemini; counts-recomputed assertion)
- [x] Full suite green: 90 passed

**Key decisions:**
- Deterministic-numbers / LLM-prose split in Agent 4: the calculator is the single
  source of truth for every figure a customer sees; Gemini only interprets. This
  makes the financial verdict trustworthy and testable without an API key.
- Agent 4 short-circuits without an LLM call when premium/term are missing
  (INSUFFICIENT_DATA) or there's no maturity benefit (NO_MATURITY_BENEFIT) —
  saves quota and returns a correct, honest answer for protection-only policies.
- Agent 5 recomputes severity counts from the flags instead of trusting Gemini's
  self-reported totals — a common LLM failure mode where the summary contradicts
  the list. Flags are also sorted worst-first for the report.
- Tuned RISK_FLAG_SYSTEM_PROMPT severity calibration after a real-doc smoke test:
  the first pass marked 15/22 flags HIGH (every exclusion escalated). Recalibrated
  so standard market-wide boilerplate (war/nuclear/suicide/self-inflicted/criminal/
  hazardous-sports) is LOW unless unusually broad, and HIGH is reserved for unusual,
  discretionary, or forfeiture/deadline clauses. Same doc now scores 5 HIGH / 7 MED
  / 7 LOW — signal restored. Prompt-only change; no agent logic touched.
- Verdict thresholds are CAGR-based (≥8% PROFIT, 4–8% BREAK_EVEN, <4% NET_LOSS),
  so a policy that grows money slower than inflation is correctly flagged.

**Next session (Day 4):** Report Composer Agent (+ report_generator.py) + full end-to-end pipeline

---

## Day 4 — Report Composer + full end-to-end pipeline ✅

**Completed:**
- [x] tools/report_generator.py — finalized (dropped Day-1 stub). Pure python-docx
      assembly, NO LLM calls. Builds the full formatted report: title + executive
      summary, policy-details table, important-dates table, coverage (covered /
      excluded / waiting periods / sub-limits), financial analysis (verdict +
      metric table + benchmark comparison), colour-coded red-flags section by
      severity, recommendation, and a footer disclaimer. Every accessor is
      defensive (None/empty → "Not specified") so it renders for a bare term
      policy and a 40-page ULIP alike.
- [x] agents/report_composer_agent.py — full Agent 6 + ADK agent factory. Digests
      Agents 2–5 output into a compact summary, asks Gemini to write ONLY the
      narrative (title, section intros, recommendation), normalizes the intros so
      every key exists, then hands everything to report_generator. Mirrors the
      numbers-vs-prose split from Agent 4 — Gemini never invents facts/figures.
- [x] pipeline.py — Agent 6 wired in with a real call + per-agent timing; now
      returns report_intros + report_bytes (genuine end-to-end .docx output).
- [x] main.py — /analyze now returns the report inline as `report_docx_base64`
      (stateless, nothing persisted to disk — matches the security model). Dropped
      the unused `io` / `Response` imports and the placeholder download-URL docstring.
- [x] tests/test_report_composer.py — 8 tests (mocked Gemini): prompt digest,
      intro normalization/fallback, real openable-.docx assertion, invalid-JSON
      path, and full + sparse-document report rendering.
- [x] Full suite green: 98 passed

**Key decisions:**
- Numbers-vs-prose split extended to Agent 6: report_generator does pure layout
  with zero LLM calls; Gemini writes only the human narrative. The report is fully
  testable without an API key (the .docx is opened and asserted on directly).
- Report is returned inline as base64 rather than via a download URL — a URL would
  require storing the bytes server-side keyed by an ID, contradicting the
  in-memory / nothing-on-disk security model. Client decodes to save the .docx.
- report_generator is defensive on every field so a protection-only policy
  (NO_MATURITY_BENEFIT, no coverage lists, no flags) still produces a clean report
  instead of KeyError-ing on the many null fields upstream agents legitimately emit.

**Next session (Day 5):** FastAPI hardening + security + testing

---

## Day 5 — FastAPI hardening + security + testing ✅

**Completed:**
- [x] tools/file_validation.py — new shared `validate_upload(file_bytes, filename)`:
      single source of truth for extension → non-empty → size → magic-bytes checks,
      raising ValueError with user-safe messages. Pure utility, no I/O, no LLM.
- [x] main.py — hardened the `/analyze` HTTP path:
      • Bounded chunked read (1 MB chunks, stop at limit+1) so an oversized or
        spoofed-Content-Length upload can never make us buffer past the limit.
      • Pre-pipeline `validate_upload` → rejects bad extension / empty / oversized /
        magic-byte-mismatch as HTTP 400 *before* any parsing or LLM work. Previously
        a disguised file (.exe renamed .pdf) reached the pipeline — magic-bytes
        validation only existed in the MCP server, which the HTTP path never calls.
      • CORSMiddleware (origins from CORS_ALLOWED_ORIGINS, credentials off, GET/POST).
      • Security-headers middleware: X-Content-Type-Options=nosniff, X-Frame-Options=DENY,
        Referrer-Policy=no-referrer, Cache-Control=no-store on every response.
- [x] config/settings.py + .env.example — added CORS_ALLOWED_ORIGINS (comma-separated,
      defaults to "*" for dev; set an explicit allow-list in production).
- [x] tests/test_main.py — 18 tests via FastAPI TestClient with run_pipeline mocked
      (no Gemini key, no API calls): info/health endpoints, security + CORS headers,
      /analyze happy path (PDF + DOCX, base64 report round-trip, null-report case),
      all four 400 rejections (bad ext / empty / magic mismatch / oversized) asserting
      the pipeline is NOT called, ValueError→422, internal error→500 with no secret
      leak, plus unit coverage of validate_upload.
- [x] Full suite green: 124 passed

**Key decisions:**
- Validation lives in one reusable module (tools/file_validation.py) rather than
  inline in main.py, so the HTTP path and any future entry point share identical
  rules. The MCP server keeps its own copy for now (it's independently tested and
  on a different transport) — deliberately not refactored to avoid churning Day-2
  tests; the magic-bytes constants are intentionally mirrored.
- Reject bad uploads at the API edge (400) instead of letting them fail deep in the
  ingestion agent (422): cheaper, clearer, and keeps the pipeline focused on
  well-formed input. 422 is now reserved for content that passes surface validation
  but can't be parsed/read.
- Bounded chunked read is a real DoS mitigation — `await file.read()` with no size
  argument buffers the whole body first, so the old "read then check size" order
  could still be forced to hold an arbitrarily large payload in memory.
- TestClient is used WITHOUT the `with` context manager so lifespan startup (which
  calls settings.validate() → needs GEMINI_API_KEY) is not triggered — tests stay
  hermetic and CI-safe with no real key.

**Next session (Day 6):** Real document testing + Docker

---

## Day 6 — Real document testing + Docker [ ] Not started

---

## Day 7 — Deploy + complete README [ ] Not started

---

## Day 8 — YouTube demo video [ ] Not started

---

## Day 9 — Kaggle Writeup [ ] Not started

---

## Day 10 — Final review + submit [ ] Not started
