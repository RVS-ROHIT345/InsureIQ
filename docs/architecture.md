# InsureIQ — Architecture

InsureIQ is a **sequential multi-agent pipeline** built on Google ADK. A user uploads
an insurance document (PDF or DOCX); six agents hand structured output down the chain,
and the final agent emits a formatted `.docx` report. Nothing is ever written to disk —
the document lives in memory for the duration of a single request and is discarded.

## High-level flow

```
Upload (PDF/DOCX)
      │
      ▼
[MCP File Server] ── extension + size + magic-bytes validation
      │
      ▼
[Agent 1: Ingestion]        → text extraction, type detection, section splitting
      ▼
[Agent 2: Policy Extractor]  → policy no., dates, premiums, maturity
      ▼
[Agent 3: Coverage Analyzer] → covered events, exclusions, waiting periods
      ▼
[Agent 4: Financial Evaluator] → total premium, CAGR, benchmark, verdict
      ▼
[Agent 5: Risk Flag]         → hidden clauses, trap dates, severity
      ▼
[Agent 6: Report Composer]   → formatted .docx (returned inline as base64)
```

The orchestration lives in [`pipeline.py`](../pipeline.py): a genuine dependency chain
where each agent consumes the previous agent's structured result — not parallel calls
behind a wrapper. Every stage is timed and logged.

## Components

### Entry points
- **`main.py`** — FastAPI app. `POST /analyze` reads the upload in bounded 1 MB chunks
  (so an oversized/spoofed upload can't exhaust memory), runs `validate_upload`, then
  invokes the pipeline and returns the report inline as base64. `GET /health` backs the
  container health check.
- **`scripts/smoke_test.py`** — runs the same six agents against a real document with the
  live Gemini API and writes the `.docx` to `output/`. This is the manual, quota-using
  sanity check (the pytest suite mocks Gemini and is the offline regression guard).

### MCP File Server (`mcp_server/file_server.py`)
An MCP server exposing `upload` and `validate` tools. It enforces extension, size, and
**magic-bytes** checks so a disguised file (e.g. an `.exe` renamed `.pdf`) is rejected
before any parsing. The same validation rules also live in `tools/file_validation.py`,
which the HTTP path uses at the API edge.

### The six agents (`agents/`)
1. **Ingestion** — extracts text (pdfplumber for PDFs, python-docx for DOCX, Gemini vision
   as a fallback for scanned PDFs), classifies the document type via a keyword fast-path
   (with a Gemini fallback for genuinely ambiguous documents), and splits the text into
   labeled sections.
2. **Policy Extractor** — pulls policy number, premiums, dates, sum assured, and maturity.
3. **Coverage Analyzer** — extracts covered events, exclusions, waiting periods, sub-limits.
4. **Financial Evaluator** — computes total premium, CAGR, and an FD/index benchmark
   comparison, then a PROFIT / BREAK_EVEN / NET_LOSS verdict.
5. **Risk Flag** — scans for hidden clauses and trap dates, assigns HIGH/MEDIUM/LOW
   severity, and recomputes the summary counts from the flags so they can't disagree.
6. **Report Composer** — assembles the final formatted `.docx` report.

### Tools (`tools/`)
- **`financial_calculator.py`** — deterministic currency/term parsing and CAGR math,
  registered as an **ADK FunctionTool** for Agent 4.
- **`report_generator.py`** — pure `python-docx` layout of the final report (no LLM calls).
- **`file_validation.py`** — shared `validate_upload()` used by the HTTP path.
- **`document_parser.py`** — PDF/DOCX text extraction with a Gemini-vision fallback.

## Key design principle: numbers vs. prose

Agents 4 and 6 deliberately separate **computation from narration**:

- Every **figure** a customer sees (premium totals, CAGR, benchmarks, report tables) is
  computed **deterministically in Python**.
- **Gemini only writes the human-readable narrative** — verdicts in plain English, section
  intros, recommendations. It never invents a number.

This is what makes the financial verdict trustworthy and lets the entire pipeline be tested
without an API key: the arithmetic and the `.docx` assembly are asserted directly, while the
LLM-authored prose is mocked.

## Security posture

- Documents processed **in memory only**, never persisted.
- Dual validation: file extension **and** magic bytes.
- Bounded chunked upload read (default 50 MB cap) as a DoS mitigation.
- Secrets exclusively from `.env` (git-ignored, `.dockerignore`-excluded).
- CORS + `nosniff` / `X-Frame-Options: DENY` / `no-store` headers on every response.
- Errors are logged server-side but never leak stack traces to the client.
- Container runs as a non-root user.

## Deployability

The app is packaged as a Docker image (`Dockerfile`) with a `HEALTHCHECK`, and a
`docker-compose.yml` for local orchestration. It honors the `$PORT` environment variable
that managed platforms (Cloud Run, Render, Railway) inject, so the same image deploys
unchanged to a live endpoint. A live public deployment is optional for the capstone; the
repository itself is the reproducible project artifact.
