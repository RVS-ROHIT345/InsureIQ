# InsureIQ — AI-Powered Insurance Document Analyzer

> A 6-agent AI system that reads the fine print so you don't have to.

[![Kaggle Capstone](https://img.shields.io/badge/Kaggle-Capstone%202026-blue)](https://www.kaggle.com)
[![Track](https://img.shields.io/badge/Track-Concierge%20Agents-green)](https://www.kaggle.com)
[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![Google ADK](https://img.shields.io/badge/Framework-Google%20ADK-red)](https://google.github.io/adk-docs/)
[![Tests](https://img.shields.io/badge/tests-192%20passing-brightgreen)](tests/)

---

## 👋 For Reviewers / Judges — Run It in 60 Seconds

The full test suite is **mocked and needs no API key** — you can verify the entire
6-agent pipeline offline:

```bash
# 1. Install
python3.11 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Run the 192-test suite (no Gemini key required — Gemini is mocked)
pytest tests/ -q
```

To see the agents run against a **real document with real Gemini calls**, add a key
and run the end-to-end smoke test (details in [Running the Live Smoke Test](#running-the-live-smoke-test)):

```bash
cp .env.example .env              # then paste your GEMINI_API_KEY into .env
python scripts/smoke_test.py      # runs all 6 agents on a bundled sample policy
```

Or start the HTTP API and analyze a document (details in [Running the API](#running-the-api)):

```bash
python main.py                    # serves on http://localhost:8000
curl -X POST http://localhost:8000/analyze \
  -F "file=@sample_docs/sample_life_insurance_limited_pay.pdf"
```

> **No live public URL is provided** — per the capstone rules, this repository *is*
> the project link (a live endpoint is optional). Everything runs locally or in Docker
> with the commands above.

---

## The Problem

Insurance documents are 40–100 pages of dense legal language designed to obscure critical details — maturity dates, penalty clauses, coverage exclusions, auto-renewal traps, and financial returns that are rarely in the customer's favor. Most people sign policies without understanding what they're paying for, when their money matures, or whether the policy is even financially worth holding.

## The Solution

InsureIQ is a 6-agent pipeline that accepts any insurance document (PDF or DOCX) and produces a plain-English summary covering:

- **Policy snapshot** — type, insurer, policyholder, sum assured
- **Coverage map** — what is covered and what is excluded
- **Critical dates** — premium due dates, grace periods, maturity date, free-look window
- **Financial analysis** — total premium paid vs. maturity benefit, effective return vs. FD and index fund benchmarks, PROFIT / BREAK-EVEN / NET LOSS verdict
- **Red flags** — hidden clauses ordered by severity (HIGH / MEDIUM / LOW)
- **Plain verdict** — is this policy worth keeping?

The output is a fully formatted **`.docx` report** returned inline (base64) so nothing is ever persisted to disk.

## Architecture

```
Upload (PDF/DOCX)
      │
      ▼
[MCP File Server] ── validation, size check, magic bytes verification
      │
      ▼
[Agent 1: Ingestion] ── text extraction (pdfplumber → Gemini vision fallback)
      │                  document type detection, section splitting
      ▼
[Agent 2: Policy Extractor] ── policy number, dates, premiums, maturity
      │
      ▼
[Agent 3: Coverage Analyzer] ── covered events, exclusions, waiting periods
      │
      ▼
[Agent 4: Financial Evaluator] ── total premium, CAGR, FD benchmark, verdict
      │         └── uses financial_calculator.py (registered ADK tool)
      ▼
[Agent 5: Risk Flag] ── hidden clauses, trap dates, severity classification
      │
      ▼
[Agent 6: Report Composer] ── structured .docx report with 7 sections
      │
      ▼
Analysis report (.docx, returned inline as base64)
```

A key design principle across Agents 4 and 6 is the **numbers-vs-prose split**: every
figure a customer sees is computed *deterministically* in Python (`financial_calculator.py`,
`report_generator.py`); Gemini only writes the human-readable narrative and never invents
a number. This makes the financial verdict trustworthy and testable without an API key.

See [docs/architecture.md](docs/architecture.md) for a deeper component-by-component write-up.

## Tech Stack

| Layer | Technology |
|---|---|
| Agent Framework | Google ADK (Agent Development Kit) |
| LLM | Gemini 2.5 Flash (1M token context — handles full insurance docs without chunking) |
| PDF Parsing | pdfplumber (tables) + Gemini vision (scanned PDFs) |
| DOCX Parsing | python-docx |
| MCP Server | mcp Python SDK |
| API | FastAPI + Uvicorn |
| Output | python-docx |
| Deployment | Docker + docker-compose (Cloud Run / Render ready — honors `$PORT`) |
| Secrets | python-dotenv (`.env` never committed) |

---

## Setup (Local)

**Prerequisite:** Python 3.11

```bash
# 1. Clone the repo
git clone https://github.com/RVS-ROHIT345/InsureIQ.git
cd InsureIQ

# 2. Create and activate a virtual environment
python3.11 -m venv venv
source venv/bin/activate          # Windows (PowerShell): venv\Scripts\Activate.ps1
                                  # Windows (cmd):        venv\Scripts\activate.bat

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env              # Windows: copy .env.example .env
# Edit .env and paste your GEMINI_API_KEY (get one at https://aistudio.google.com/app/apikey)
```

> The **test suite needs no key** (Gemini is mocked). A key is only required for the
> live smoke test and the running API, which make real Gemini calls.

## Running the API

```bash
python main.py
# → InsureIQ API on http://localhost:8000
```

Endpoints:

| Method | Path | Description |
|---|---|---|
| `POST` | `/analyze` | Upload a PDF/DOCX insurance document, receive the full analysis |
| `GET`  | `/health` | Health check (used by Docker / Cloud Run) |
| `GET`  | `/` | API info |

**Analyze a document:**

```bash
curl -X POST http://localhost:8000/analyze \
  -F "file=@sample_docs/sample_life_insurance_limited_pay.pdf"
```

**Response shape** (`report_docx_base64` decodes to the formatted `.docx` report):

```json
{
  "status": "success",
  "filename": "sample_life_insurance_limited_pay.pdf",
  "document_type": "life",
  "policy_data": { "policy_number": "...", "maturity_date": "...", "...": "..." },
  "coverage_map": { "covered_events": ["..."], "excluded_events": ["..."], "waiting_periods": ["..."], "sub_limits": ["..."] },
  "financial_verdict": { "verdict": "NET_LOSS", "effective_annual_return_pct": 3.2, "total_premium_paid": "...", "maturity_benefit": "...", "...": "..." },
  "risk_flags": { "flags": ["..."], "overall_risk_level": "MEDIUM" },
  "report_intros": { "title": "...", "...": "..." },
  "report_docx_base64": "UEsDBBQABgAI...",
  "metadata": { "document_type": "life", "extraction_method": "pdfplumber", "pipeline_duration_seconds": 12.3 }
}
```

Interactive docs (Swagger UI) are available at **http://localhost:8000/docs** while the API is running.

## Running the Tests

The pytest suite is **fully mocked** — no Gemini key, no network, no quota. It runs in
~10s and covers every agent's logic, the financial calculator's arithmetic, the FastAPI
layer, file validation, and the sample-document corpus.

```bash
pytest tests/ -q
# → 192 passed
```

## Running the Live Smoke Test

This runs the **real** pipeline end-to-end (all 6 agents) against a real document using
the **live Gemini API**, prints each agent's output, and writes the final `.docx` to
`output/`. It requires a valid `GEMINI_API_KEY` in `.env` and makes ~6 real API calls.

```bash
# Uses the bundled sample life-insurance policy
python scripts/smoke_test.py

# …or point it at your own document
python scripts/smoke_test.py path/to/your_policy.pdf
```

A successful run ends with `✅ Smoke test passed` and saves
`output/<doc>_insureiq_report.docx` for you to open and inspect.

> **Hit the Gemini free-tier quota?** If the key runs out of usage/rate limit, InsureIQ
> stops with a clear, explicit message — the smoke test prints
> `⚠️ Gemini API quota exhausted …` and the API returns **HTTP 429** with the same
> guidance (not a cryptic 500). This is expected free-tier behaviour, **not a bug**.
> You can wait for the quota to reset (per-minute limits clear in ~60s; the free daily
> limit resets after ~24h), swap in a different `GEMINI_API_KEY`, or just run the mocked
> test suite (`pytest tests/ -q`), which needs no API calls at all.

## Setup (Docker)

```bash
# Build and run (reads GEMINI_API_KEY from your .env)
docker-compose up --build
# API available at http://localhost:8000  (health-checked automatically)
```

The image runs as a non-root user, contains no secrets (`.env` is excluded via
`.dockerignore`), and defines a `HEALTHCHECK` that probes `/health`. Because the app
honors `$PORT`, the same image deploys unchanged to Cloud Run or Render.

## Sample Documents

Realistic (synthetic) policies are bundled in [`sample_docs/`](sample_docs/) for testing,
covering all four supported types in both PDF and DOCX:

| Type | Files |
|---|---|
| Life | `sample_life_insurance_policy.docx`, `sample_life_insurance_limited_pay.pdf` |
| Health | `sample_health_insurance_policy.pdf` / `.docx` |
| Car | `sample_car_insurance.pdf` / `.docx`, `sample_car_insurance_cover_note.*` (sparse edge case) |
| Home | `sample_home_insurance.pdf` / `.docx` |

## Project Structure

```
insureiq/
├── main.py                     # FastAPI entry point (POST /analyze, /health)
├── pipeline.py                 # Orchestrates the 6-agent pipeline
├── agents/                     # The six agents (ingestion → report composer)
├── tools/                      # financial_calculator, report_generator, file_validation, document_parser
├── mcp_server/                 # MCP file server (upload + validate tools)
├── config/                     # settings.py + agent_prompts.py
├── scripts/                    # smoke_test.py, demo_run.py
├── sample_docs/                # Bundled test documents (all 4 types, PDF + DOCX)
├── tests/                      # 192 mocked tests (no API key needed)
├── docs/architecture.md        # Deeper architecture write-up
├── Dockerfile / docker-compose.yml
└── requirements.txt
```

## Kaggle Course Concepts Demonstrated

| Concept | Where |
|---|---|
| Multi-agent system (ADK) | `pipeline.py` + all 6 agent files in `agents/` |
| MCP Server | `mcp_server/file_server.py` |
| Agent Skills (ADK tools) | `tools/financial_calculator.py` registered as an ADK FunctionTool |
| Security features | Input validation, magic-bytes checks, `.env` secrets, in-memory processing |
| Deployability | `Dockerfile`, `docker-compose.yml`, `$PORT`-aware, Cloud Run / Render ready |

## Security

- No API keys or secrets in code — all loaded from `.env` (which is git-ignored and never committed)
- User documents are processed **in memory only** — never written to disk
- File type validated by **both** extension **and** magic bytes (a `.exe` renamed `.pdf` is rejected)
- Upload size bounded with a chunked read (default 50 MB) — an oversized/spoofed upload can't exhaust memory
- CORS + conservative security headers (`nosniff`, `X-Frame-Options: DENY`, `no-store`) on every response
- Error responses never expose internal stack traces
- Container runs as a non-root user

## License

MIT

---

*Built for the Kaggle AI Agents Intensive Vibe Coding Capstone — Concierge Agents track*
