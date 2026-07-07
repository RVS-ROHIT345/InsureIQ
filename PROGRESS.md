# InsureIQ — Build Progress Log

Track: Concierge Agents
Deadline: July 6, 2026 at 11:59 PM PT (⚠️ verify against the live Kaggle page — the
  official rules PDF snapshot read "10 days to go", so confirm the real close date)
GitHub: https://github.com/RVS-ROHIT345/InsureIQ
Live URL: none — deployment is OPTIONAL per the capstone rules ("Participants are not
  required to deploy their agents to a live public endpoint"). The GitHub repo, with
  detailed run instructions, is the submission's Project Link.

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

## Day 6 — Real document testing + Docker ✅

**Completed:**
- [x] scripts/generate_sample_docs.py — new committed, reproducible generator that
      produces realistic *synthetic* health/car/home policies in BOTH PDF (ReportLab)
      and DOCX (python-docx), plus a deliberately-sparse car "cover note" edge case.
      Idempotent (skips existing files unless --force), so the hand-tuned Day-2 life
      fixtures are left untouched. Each doc weaves in enough type-specific vocabulary
      (config.DOC_TYPE_KEYWORDS) that the keyword classifier resolves the type with
      NO Gemini call — which is what makes the corpus testable offline.
- [x] sample_docs/ — corpus now covers all four advertised types: health (pdf+docx),
      car (pdf+docx), home (pdf+docx), sparse car cover-note (docx), + existing life
      (pdf+docx). 9 fixtures total, every one validated/parsed/classified.
- [x] tests/test_sample_docs.py — 29 offline tests (no quota): every fixture passes
      validate_upload (extension + magic bytes), extracts readable text above the
      50-char ingestion floor, and classifies to its expected type via the keyword
      detector. Plus two guard tests: all four types have a fixture, and EXPECTED_TYPE
      stays in lock-step with what's actually on disk (a new sample_docs/ file that
      isn't mapped fails the suite).
- [x] requirements.txt — added reportlab==4.2.5 in a clearly-marked dev/test section
      (mirrors how pytest already lives there). Not imported by the app at runtime;
      the new .dockerignore keeps scripts/ out of the production image.
- [x] .dockerignore — NEW. Excludes venv/, .git/, .env*, __pycache__, .pytest_cache,
      tests/, scripts/, sample_docs/, output/, docs/, *.md, editor config. Fixes a real
      problem: `COPY . .` was previously copying the entire context — including the
      ~venv and, critically, .env — straight into the image.
- [x] .gitignore — removed the stray `.dockerignore` ignore rule so the new
      .dockerignore is actually committed (a .dockerignore only works if it ships).
- [x] Dockerfile + docker-compose.yml — fixed a broken health check: the compose file
      probed with `curl`, which the python:3.11-slim image never installs (health check
      would have failed forever). Replaced both with a Python-stdlib urllib probe of
      /health, and added a matching HEALTHCHECK to the Dockerfile so `docker run` alone
      is health-checked (not just compose).
- [x] Verified the container end-to-end: built the image, ran it with a dummy
      GEMINI_API_KEY, confirmed GET /health → 200 (with security headers) and GET /
      → API info, the Docker HEALTHCHECK transitions to "healthy", and .env / venv /
      tests are all absent from the built image.
- [x] Full suite green: 153 passed (was 124; +29 sample-doc tests).

**Key decisions:**
- "Real document testing" is split into two layers: a deterministic, quota-free
  offline layer (test_sample_docs.py — validation + parse + keyword classification
  across all 4 types, runs in CI with no key) and the existing on-demand live layer
  (scripts/smoke_test.py — the LLM-dependent tail). The offline layer is the
  regression guardrail; the live run stays a manual, quota-sparing sanity check per
  the standing testing convention. The assistant did NOT run the live smoke test.
- Sample docs are self-describing by design: enough type keywords in the first page
  that the keyword classifier (needs 2+ matches) resolves the type without falling
  back to Gemini. That's both realistic AND what lets the fixtures be asserted on
  offline — the front half of the pipeline is now fully testable without a key.
- Health check uses a Python urllib probe rather than installing curl: the slim
  image has Python already, so no extra apt layer / image weight just to health-check.
- reportlab is dev/test-only. Rather than a separate requirements-dev.txt (new
  convention), it goes in requirements.txt next to pytest — matching the project's
  existing one-file convention — and .dockerignore keeps scripts/ out of the image
  so the dependency is never actually needed at runtime.
- Image is ~981 MB, dominated by the mandatory google-adk / google-cloud-aiplatform
  stack (unavoidable given the Kaggle ADK requirement), not by build-context cruft —
  the .dockerignore removed the venv/secret bloat that was the fixable part.

**Day 6 follow-up — real user-supplied documents + classifier hardening:**
- [x] The user replaced the synthetic fixtures with their own realistic documents
      (health/car/home policies + a car cover note, in PDF and DOCX — real ~190 KB
      PDFs). Re-ran the offline suite against them, which surfaced real classifier
      behaviour the clean synthetic docs had hidden.
- [x] agents/ingestion_agent.py — added a CONFIDENCE MARGIN to the keyword
      fast-path: it now trusts a type only when it has ≥2 matches AND leads the
      runner-up by ≥2 (MIN_KEYWORD_SCORE / KEYWORD_CONFIDENCE_MARGIN constants).
      Fixes a genuine misclassification: the user's health fixture is a hybrid
      "Health Cum Savings Endowment" plan scoring life:3 vs health:2 — the old
      "≥2 wins" rule confidently (and wrongly) picked `life` and skipped the Gemini
      fallback. A bare 3-vs-2 edge is no longer "confident"; close calls defer to
      Gemini, which reads meaning rather than counting keywords.
- [x] agents/ingestion_agent.py — widened the keyword scan window 3000 → 6000 chars
      (KEYWORD_SAMPLE_CHARS). python-docx appends all tables *after* the body text,
      so a car schedule's keywords (own damage / third party / IDV) sat past the old
      3000-char cutoff and the DOCX punted while the same PDF classified. Verified the
      wider window introduces no confident-wrong answers on the corpus.
- [x] config/settings.py — added US-style homeowners vocabulary to the `home`
      keyword list (`homeowners policy`, `dwelling`, `personal property`,
      `loss of use`) so US HO-3 policies classify on the fast-path. Verified these
      terms do NOT appear in any health/life/car fixture (no cross-type leakage).
- [x] tests/test_sample_docs.py — updated EXPECTED_TYPE to the user's filenames and
      reframed the classification test to the correct real-doc invariant: the keyword
      fast-path may return the right type OR punt to `unknown` (→ Gemini at runtime),
      but must NEVER be confidently wrong. This is the property that actually matters
      and is offline-verifiable without a key.
- [x] Result on the user's corpus: 8/10 classify correctly on the fast-path, 2 (the
      genuine health-endowment hybrids) correctly punt to Gemini, 0 confidently wrong.
      Full suite green: 156 passed.

**Key decisions (follow-up):**
- The `document_type` label does NOT change what downstream agents extract, so these
  classifier fixes are a robustness / quota-and-latency improvement (fewer Gemini
  classification calls, graceful degradation if Gemini is rate-limited) — NOT an
  output-accuracy change. Runtime type was already correct via the fallback.
- Genuinely ambiguous documents (a health-cum-savings hybrid) are left to punt to
  Gemini on purpose. Forcing a keyword answer there would trade a correct "ask the
  smarter classifier" for a brittle guess — the wrong kind of fix.

**Next session (Day 7):** Deploy + complete README

---

## Day 7 — Complete README + repo polish (deployment scoped as optional) ✅

**Rules check first:** Read the official capstone rules (AiChallengeCompleteInfo). Key
findings that reshaped this day:
- A live deployment is **NOT required** — "Participants are not required to deploy their
  agents to a live public endpoint for judging purposes." A public GitHub repo with
  detailed setup instructions satisfies the Project Link requirement.
- Documentation is worth **20 points** and must be a README covering problem, solution,
  architecture, setup, and diagrams. That's where the effort went.
- Deployability is one of six concepts (need ≥3); it's satisfied by the Docker/Compose
  setup + $PORT-readiness in code and shown in the video — no live URL needed.

**Completed:**
- [x] README.md — rewritten as a judge-runnable document:
      • "For Reviewers / Judges — Run It in 60 Seconds" block up top (install → 178-test
        suite with NO key → smoke test / API).
      • Explicit, accurate sections: Running the API (endpoints + example request/response
        + Swagger link), Running the Tests (mocked, keyless), Running the Live Smoke Test
        (real Gemini), Docker, Sample Documents table, Project Structure.
      • Fixed the real GitHub clone URL, the actual sample-doc filenames, and the tests
        badge (178 passing).
      • Corrected the model reference (was "Gemini 1.5 Pro" → actual "Gemini 2.5 Flash").
      • Reframed deployment as Cloud Run / Render *ready* rather than done, matching reality.
- [x] docs/architecture.md — expanded from a one-line stub into a full component-by-component
      write-up (flow diagram, entry points, MCP server, the six agents, tools, the
      numbers-vs-prose principle, security posture, deployability). README links to it.
- [x] config/settings.py — API_PORT now honors `$PORT` first (Cloud Run/Render/Railway
      inject it), then API_PORT, then 8000. Makes the "deploy-ready" claim genuinely true
      and unblocks any future one-command deploy.
- [x] .env.example — API_PORT 8002 → 8000 to match the Dockerfile/compose/health-check
      (a judge copying .env.example would otherwise have run the app on a port nothing
      else probed).
- [x] agents/gemini_utils.py — reviewer-friendly quota handling. New
      GeminiQuotaExhaustedError + _is_quota_error detection: a used-up free-tier key now
      fails fast (no pointless retries on a daily quota) with a plain-English, actionable
      message instead of an opaque RuntimeError. main.py maps it to HTTP 429 (not 500);
      scripts/smoke_test.py prints "⚠️ Gemini API quota exhausted …" and exits cleanly.
      README documents the behaviour so a judge who hits the limit understands it's
      expected, not a crash.
- [x] tests/test_gemini_utils.py (new) + a 429 case in test_main.py — 14 new tests
      covering quota detection, fail-fast, non-quota retry, and the 429 mapping.
- [x] Full suite still green: 192 passed (was 178; +14).

**Key decisions:**
- Deployment deliberately treated as optional after reading the rules — the guaranteed
  points are in Documentation (20 pts) and a repo that actually runs, so Day 7 targets
  those instead of burning the deadline on gcloud/billing setup.
- The `$PORT` fix is universal (works for Cloud Run, Render, Railway, Heroku), so the repo
  stays genuinely deploy-ready without committing to any one platform.
- README leads with the keyless 178-test suite so a judge can verify the whole pipeline
  offline in under a minute — the strongest possible "instructions that actually run."

**Next session (Day 8):** YouTube demo video (Antigravity + Deployability shown here)

---

## Day 8 — Submission demo video kit ✅

**Antigravity check (did it first):** Searched the whole repo — no `.antigravity/`
config, no IDE metadata, no commit signatures, nothing. The only two mentions of
"antigravity" were the *claim* rows in PROGRESS/README, not build evidence. This
project was built with Claude Code, not Antigravity. Rather than fake it on camera,
we **dropped the Antigravity claim** — the repo genuinely demonstrates 5 of the 6
course concepts (multi-agent/ADK, MCP, ADK tools, security, deployability), well
above the ≥3 required, so the claim was unnecessary risk.

**Completed:**
- [x] README.md — removed the unsupported "Antigravity | Demonstrated in the
      submission video" row from the Course Concepts table. No false claim to judges.
- [x] docs/demo_video_script.md — NEW. Word-for-word narration + shot list keyed to
      the capstone's exact required structure (0:00 problem / 0:45 why-agents /
      1:30 architecture / 2:30 live demo / 4:00 tech stack). Includes a recording
      checklist and a "record a good take first as quota insurance" plan.
- [x] scripts/demo_run.py — NEW. Screen-recording-friendly pipeline driver for the
      2:30–4:00 live-demo segment. Runs one real doc through all 6 agents narrating
      each hand-off with a timing, then prints an AT-A-GLANCE panel highlighting the
      exact three things the rubric wants shown: maturity date (Agent 2), financial
      verdict + IRR/benchmarks (Agent 4), and severity-rated red flags (Agent 5).
      Formatted for a viewer (ANSI colour, box-drawing, `--no-color` fallback), not
      raw JSON like smoke_test.py. Makes REAL Gemini calls; the user records it.
- [x] docs/architecture_diagram.html — NEW. Polished, theme-aware "document-intelligence
      transit line" diagram of the 6-agent pipeline for the 1:30–2:30 architecture
      segment: the policy rides a rail through 6 numbered stations, every connector
      labelled with the real data hand-off (text+type → policy facts → coverage →
      verdict → flags → .docx). Rebuilt from a flat six-box row after review.
- [x] images/architecture_diagram_{dark,light}.png — NEW. Rendered the diagram to
      3200×1800 (2× retina, 16:9) PNGs via headless Chrome so the diagram can be
      dropped straight into the video / slides without a live URL. Both themes.
- [x] docs/why_agents.html + images/why_agents_{dark,light}.png — NEW. The
      single-LLM-call vs 6-agents comparison graphic for the 0:45–1:30 "why agents"
      segment (was only described in the script, no image existed). Same visual
      system as the architecture diagram; rendered to 3200×1800 PNGs, both themes.
- [x] Removed scripts/generate_sample_docs.py (the Day-6 synthetic-doc generator) —
      the corpus is now the user's own real documents, so the generator is unused.
      Dropped its sole dependency `reportlab` from requirements.txt and updated the
      two README references. No test imported it; suite unaffected.

**Key decisions:**
- Honesty over concept-count: dropped a claim we couldn't back rather than staging
  fake Antigravity footage. 5 genuine concepts already clears the bar.
- The live demo uses a dedicated `demo_run.py` (viewer-formatted) instead of
  `smoke_test.py` (developer-formatted, dumps JSON) — the AT-A-GLANCE panel is built
  to be the on-camera payoff. Default doc is the limited-pay LIFE policy because it's
  the only type that exercises maturity date + full financial verdict + red flags all
  at once (term/health have no maturity → duller demo).
- Architecture segment is served by a real diagram, not a code scroll — a judge
  parses the 6-agent flow far faster from a visual.
- Assistant did NOT run demo_run.py (real Gemini calls / quota convention) — the user
  records it live. Script tells them to capture one good take first as insurance
  against a mid-recording quota exhaustion (which now prints cleanly, not a crash).

**Next session (Day 9):** Kaggle Writeup

---

## Day 9 — Kaggle Writeup ✅

**Completed:**
- [x] docs/kaggle_writeup.md — NEW. Complete, paste-ready Kaggle submission writeup
      following the capstone's required structure: links block (YouTube + GitHub +
      "verify offline") → Problem → Solution → Why multi-agent → Architecture (6-agent
      table) → Demo → Tech stack → Course concepts (honest 5-of-6) → Engineering
      highlights → 60-second run instructions. Kept in lock-step with the README
      (192 tests, Gemini 2.5 Flash, numbers-vs-prose split) and Day-8's dropped
      Antigravity claim — no concept is overstated.
- [x] YouTube demo video recorded, uploaded, and linked: https://youtu.be/eyj7NNDGuvo
      (embedded in both the links table and the Demo section).
- [x] Diagram images embedded via GitHub **raw** URLs
      (raw.githubusercontent.com/.../main/images/...) rather than relative paths, so
      both the why-agents and architecture PNGs render inline when the markdown is
      pasted into the Kaggle Writeup editor (relative paths only resolve on GitHub).

**Key decisions:**
- Wrote the writeup as a committed repo file (docs/kaggle_writeup.md) so the submission
  text is version-controlled and consistent with the README/architecture docs, then
  pasted into Kaggle — single source of truth, no drift between repo and submission.
- Used GitHub raw image URLs because Kaggle's editor won't resolve repo-relative paths;
  the PNGs are already on origin/main (verified) so the links are live.
- Concept count stays at a genuine 5-of-6 (no Antigravity) — matches Day 8's honesty
  decision; nothing in the writeup claims more than the repo demonstrates.

**Next session (Day 10):** Final review + submit

---

## Day 10 — Final review + submit ✅

**Final pre-submission review (all green):**
- [x] Keyless test suite: **192 passed** (Gemini mocked, ~8s, no API key).
- [x] Repo hygiene: working tree clean, in sync with origin/main (0 ahead / 0 behind).
- [x] Cross-doc consistency swept (README, kaggle_writeup, architecture,
      demo_video_script): test count is **192** everywhere; LLM is **Gemini 2.5 Flash**
      everywhere (no stale "1.5 Pro"); the **Antigravity claim is fully removed** from
      README and all docs (matches the Day-8 honesty decision — genuine 5-of-6 concepts).
- [x] External links verified live (they're what a judge actually loads from the Kaggle
      writeup): both GitHub **raw** image URLs (architecture_diagram_dark.png,
      why_agents_dark.png) return HTTP 200 with sizes matching the local PNGs; the
      YouTube demo (https://youtu.be/eyj7NNDGuvo) is public and viewable
      (title "InsureIQ — 6 AI Agents That Read Insurance Fine Print for You | Kaggle
      Capstone 2026" served by YouTube).
- [x] Secret hygiene confirmed: `.env` is untracked and in `.gitignore`; a full
      git-history scan for a real Gemini key (`AIza…`) came back empty. Repo is safe
      to be the public submission link.

**Remaining manual step — the user submits on Kaggle** (assistant can't do this):
- [ ] Paste docs/kaggle_writeup.md into the Kaggle Writeup editor.
- [ ] Set the Project Link to the GitHub repo (https://github.com/RVS-ROHIT345/InsureIQ)
      and confirm the YouTube link is attached.
- [ ] ⚠️ Verify the real close date on the live Kaggle competition page before the
      deadline (the rules PDF snapshot read "10 days to go"; treat July 6 as the working
      deadline until confirmed) and click Submit.

**Key decisions:**
- Verified the *external* dependencies of the submission (raw image URLs + video),
  not just local files — a repo-relative or broken image is invisible in local review
  but blank in the Kaggle editor, and those URLs only go live once pushed to main.
- Left the actual Kaggle submission as a user action by design: it requires the user's
  Kaggle account and a human read of the live deadline, which the assistant can't and
  shouldn't automate.
