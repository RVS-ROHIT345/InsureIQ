# InsureIQ — AI-Powered Insurance Document Analyzer

> A 6-agent AI system that reads the fine print so you don't have to.

[![Kaggle Capstone](https://img.shields.io/badge/Kaggle-Capstone%202026-blue)](https://www.kaggle.com)
[![Track](https://img.shields.io/badge/Track-Concierge%20Agents-green)](https://www.kaggle.com)
[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![Google ADK](https://img.shields.io/badge/Framework-Google%20ADK-red)](https://google.github.io/adk-docs/)

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
Download analysis report (.docx)
```

## Tech Stack

| Layer | Technology |
|---|---|
| Agent Framework | Google ADK (Agent Development Kit) |
| LLM | Gemini 1.5 Pro (1M token context window) |
| PDF Parsing | pdfplumber (tables) + Gemini vision (scanned PDFs) |
| DOCX Parsing | python-docx |
| MCP Server | mcp Python SDK |
| API | FastAPI |
| Output | python-docx |
| Deployment | Docker + Google Cloud Run |
| Secrets | python-dotenv (.env never committed) |

## Setup (Local)

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/insureiq.git
cd insureiq

# 2. Create virtual environment
python3.11 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# 5. Run the API
python main.py

# 6. Test with a document
curl -X POST http://localhost:8000/analyze \
  -F "file=@sample_docs/sample_life_insurance_limited_pay.pdf"
```

## Setup (Docker)

```bash
# Build and run
docker-compose up --build

# API available at http://localhost:8000
```

## API Usage

```bash
# Analyze an insurance document
curl -X POST https://YOUR_CLOUD_RUN_URL/analyze \
  -F "file=@your_policy.pdf"

# Health check
curl https://YOUR_CLOUD_RUN_URL/health
```

## Kaggle Course Concepts Demonstrated

| Concept | Where |
|---|---|
| Multi-agent system (ADK) | `pipeline.py` + all 6 agent files |
| MCP Server | `mcp_server/file_server.py` |
| Agent Skills | `tools/financial_calculator.py` registered as ADK FunctionTool |
| Security features | Input validation, .env secrets, in-memory processing |
| Deployability | `Dockerfile`, `docker-compose.yml`, Cloud Run deployment |
| Antigravity | Demonstrated in YouTube video |

## Security

- No API keys or secrets in code — all loaded from `.env`
- `.env` is in `.gitignore` — never committed
- User documents are processed in memory only — never written to disk
- File type validated by both extension AND magic bytes
- File size limited to 50 MB
- Error responses never expose internal implementation details

## License

MIT

---

*Built for Kaggle AI Agents Intensive Vibe Coding Capstone — Concierge Agents track*
*Deadline: July 6, 2026*
