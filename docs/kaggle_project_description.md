## The Problem

Insurance documents are 40–100 pages of dense legal language engineered to obscure the
details that matter — maturity dates, penalty clauses, coverage exclusions, auto-renewal
traps, and returns that rarely favor the customer. Most people sign without understanding
what they're paying for, when their money matures, or whether the policy is even worth
holding versus simply leaving the money in a bank.

Three questions decide whether a policy is good or bad, and almost nobody can answer them
from the document itself:

1. **When does my money mature** — and what penalties gate the dates in between?
2. **Is this financially a good deal**, or am I losing to inflation?
3. **What's the fine print** that could get a claim denied?

## The Solution

**InsureIQ** accepts any insurance policy — **life, health, motor, or home** — as a PDF or
DOCX and runs it through a chain of six specialized agents, producing a plain-English
analysis and a fully formatted `.docx` report covering:

- **Policy snapshot** — type, insurer, policyholder, sum assured
- **Coverage map** — what is covered vs. excluded, waiting periods, sub-limits
- **Critical dates** — premium due dates, grace periods, maturity date, free-look window
- **Financial verdict** — total premium paid vs. maturity benefit, effective annual return
  benchmarked against a fixed deposit and an index fund → **PROFIT / BREAK-EVEN / NET LOSS**
- **Red flags** — hidden clauses ordered by severity (HIGH / MEDIUM / LOW), with genuinely
  unusual clauses called out separately from standard boilerplate
- **A plain verdict** — is this policy worth keeping?

The report is returned inline (base64) so **nothing is ever persisted to disk**.

## Why a Multi-Agent System

The obvious approach — paste the whole document into one prompt and ask a model to
"analyze it" — fails in ways that matter for money. A single call blends jobs that need
different kinds of thinking (classifying, extracting exact figures, doing arithmetic,
judging risk), and it will happily **hallucinate a maturity value or an interest rate**
because it's just predicting text.

InsureIQ splits the work across six focused agents, each with one job. The most important
consequence is the **numbers-vs-prose split**: every figure a customer sees is computed by
real, deterministic Python code (`financial_calculator.py`, `report_generator.py`), and the
model only writes the plain-English narrative *around* numbers it is never allowed to
invent. That's the difference between a demo and something you'd trust with a financial
decision.

![Single call vs. six agents](https://raw.githubusercontent.com/RVS-ROHIT345/InsureIQ/main/images/why_agents_dark.png)

## Architecture — The 6-Agent Pipeline

A document enters through an **MCP file server** that validates it by extension *and* magic
bytes (a virus renamed `.pdf` is rejected at the door). Six agents then run in sequence,
each handing structured output to the next:

![The 6-agent pipeline](https://raw.githubusercontent.com/RVS-ROHIT345/InsureIQ/main/images/architecture_diagram_dark.png)

| # | Agent | Job | Output handed forward |
|---|---|---|---|
| 1 | **Ingestion** | Extract text (pdfplumber → Gemini vision fallback for scans), detect document type | text + type |
| 2 | **Policy Extractor** | Pull structured facts: premium, sum assured, dates, **maturity date** | policy facts |
| 3 | **Coverage Analyzer** | Separate covered from excluded events, waiting periods, sub-limits | coverage map |
| 4 | **Financial Evaluator** | Compute effective annual return via a registered **ADK calculator tool**, benchmark vs. FD + index fund, return a verdict | financial verdict |
| 5 | **Risk Flag** | Surface fine-print traps, rate severity, distinguish boilerplate from unusual clauses | rated red flags |
| 6 | **Report Composer** | Assemble everything into a formatted, plain-English `.docx` report | report (base64) |

This is a genuine dependency chain built on **Google's Agent Development Kit (ADK)** — not
parallel calls with a wrapper on top. A deeper component-by-component write-up lives in
[`docs/architecture.md`](https://github.com/RVS-ROHIT345/InsureIQ/blob/main/docs/architecture.md).

## Demo

The 5-minute demo video walks through the problem, the multi-agent rationale, the
architecture, and a **live end-to-end run** on a real 14-page life-insurance policy —
showing the six agents fire in order and the final report opened in Word.

▶️ **Watch the demo:** https://youtu.be/eyj7NNDGuvo

## Tech Stack

| Layer | Technology |
|---|---|
| Agent framework | Google ADK (Agent Development Kit) |
| LLM | Gemini 2.5 Flash (1M-token context — full docs, no chunking) |
| PDF parsing | pdfplumber (tables) + Gemini vision (scanned PDFs, no OCR dependency) |
| DOCX parsing | python-docx |
| File intake | MCP server (mcp Python SDK) |
| API | FastAPI + Uvicorn |
| Report output | python-docx |
| Deployment | Docker + docker-compose, `$PORT`-aware (Cloud Run / Render ready) |
| Secrets | python-dotenv (`.env` never committed) |

## Kaggle Course Concepts Demonstrated

InsureIQ genuinely demonstrates **5 of the 6** course concepts — comfortably above the ≥3
required:

| Concept | Where in the repo |
|---|---|
| **Multi-agent system (ADK)** | `pipeline.py` orchestrating all 6 agents in `agents/` |
| **MCP server** | `mcp_server/file_server.py` (upload + validate tools) |
| **Agent Skills / ADK tools** | `tools/financial_calculator.py` registered as an ADK `FunctionTool` |
| **Security features** | Input validation, magic-bytes checks, `.env` secrets, in-memory processing |
| **Deployability** | `Dockerfile`, `docker-compose.yml`, `$PORT`-aware, Cloud Run / Render ready |

## Engineering Highlights

- **Numbers-vs-prose split** — the financial verdict is computed deterministically in
  Python; the model cannot invent a return rate. The verdict is trustworthy *and* testable
  without an API key.
- **Testable for free** — a **192-test suite mocks Gemini**, so a reviewer can verify the
  entire pipeline offline, no key, no quota, in under a minute (`pytest tests/ -q`).
- **Graceful free-tier handling** — a used-up Gemini key fails fast with a clear message and
  an HTTP 429 (not a cryptic 500), so reviewers who hit the quota see expected behavior, not
  a crash.
- **Security posture** — uploads validated by extension *and* magic bytes, bounded chunked
  reads (DoS-safe), documents processed **in memory only**, conservative security headers on
  every response, container runs as non-root.
- **Tested across policy types** — a keyless fixture suite validates and classifies real
  life, health, motor, and home documents (plus a deliberately sparse motor "cover note"
  edge case), so breadth is proven offline without an API key.

## How to Run It

### Step 1 — Install & verify offline (60 seconds, no API key)

The full pipeline is verifiable with **no Gemini key** — the 192-test suite mocks the model:

```bash
git clone https://github.com/RVS-ROHIT345/InsureIQ.git
cd InsureIQ
python3.11 -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
pytest tests/ -q                                       # → 192 passed (Gemini mocked)
```

### Step 2 — Watch all 6 agents run on a real document (needs an API key)

To see the real pipeline end-to-end — each of the six agents firing in sequence on a real
policy and the final `.docx` report written out — add a free Gemini key and run the smoke test:

```bash
cp .env.example .env                        # Windows: copy .env.example .env
# paste your GEMINI_API_KEY into .env  (get one free at https://aistudio.google.com/app/apikey)

python scripts/smoke_test.py                # runs all 6 agents on a bundled sample policy
# …or point it at your own document:
python scripts/smoke_test.py path/to/your_policy.pdf
```

The smoke test prints **each agent's output as it runs** (Ingestion → Policy Extractor →
Coverage Analyzer → Financial Evaluator → Risk Flag → Report Composer), makes ~6 real Gemini
calls, ends with `✅ Smoke test passed`, and saves the formatted report to
`output/<doc>_insureiq_report.docx` for you to open.

> **Hit the free-tier quota?** InsureIQ stops with a clear `⚠️ Gemini API quota exhausted`
> message (and the API returns HTTP 429, not a cryptic 500) — this is expected free-tier
> behavior, **not a bug**. Wait for the limit to reset, swap in another key, or just run the
> keyless test suite from Step 1.

### Alternative — run it as an API

```bash
python main.py                              # serves on http://localhost:8000
curl -X POST http://localhost:8000/analyze \
  -F "file=@sample_docs/sample_life_insurance_limited_pay.pdf"
```

Interactive Swagger docs are at `http://localhost:8000/docs`. Full instructions are in the
[README](https://github.com/RVS-ROHIT345/InsureIQ/blob/main/README.md).

> Per the capstone rules, a live public endpoint is optional — **this repository is the
> project link**. Everything runs locally or in Docker.

---

*Built for the Kaggle AI Agents Intensive Vibe Coding Capstone — Concierge Agents track.*
