# InsureIQ — Submission Video Script & Shot List

**Target length:** ~5 minutes · **Record with:** OBS Studio or Loom · **Upload:** YouTube, public or unlisted.

This script follows the capstone's required structure exactly. Each block has
**[ON SCREEN]** (what to show / record) and **[SAY]** (word-for-word narration —
read it or paraphrase). Timings are targets, not handcuffs; the live demo (2:30–4:00)
is the segment judges care about most, so protect that time.

> **Before you hit record**, run the *Recording Checklist* at the bottom once.

---

## 0:00 – 0:45 · Problem statement

**[ON SCREEN]** Open a real insurance PDF full-screen — use
`sample_docs/sample_life_insurance_limited_pay.pdf`. Slowly scroll through a dense
page of clauses, exclusions, and fine print. Let it look overwhelming.

**[SAY]**
> "This is a real insurance policy. It's fourteen pages of clauses like this one.
> Somewhere in here is the answer to three questions every policyholder actually
> cares about: *When does my money mature? Is this policy actually a good deal, or
> am I losing to inflation? And what's the fine print that could deny my claim?*
> Almost nobody reads all of this — and the people who wrote it know that.
> InsureIQ reads it for you, in about thirty seconds, and answers those three
> questions in plain English."

---

## 0:45 – 1:30 · Why a multi-agent system

**[ON SCREEN]** Show the comparison graphic full-screen —
`images/why_agents_dark.png` (or `_light`): on the left, "one giant prompt → one LLM
call" with its failure modes; on the right, "6 focused agents in a chain" with the
wins. Talk down the two columns.

**[SAY]**
> "The obvious approach is to paste the whole document into one big prompt and ask
> a model to 'analyze it.' That fails in ways that matter for money. A single call
> blends together jobs that need different kinds of thinking — classifying the
> document, pulling exact figures, doing arithmetic, and judging risk — and it will
> happily *hallucinate a maturity value or an interest rate* because it's just
> predicting text.
>
> InsureIQ splits the work across six specialized agents, each with one job and one
> focused prompt. The most important consequence: the financial numbers are computed
> by real, deterministic code — not guessed by the model. The model only writes the
> plain-English explanation *around* numbers it isn't allowed to invent. That's the
> difference between a demo and something you'd trust with a financial decision."

---

## 1:30 – 2:30 · Architecture — the 6-agent pipeline

**[ON SCREEN]** Show the architecture diagram full-screen —
`images/architecture_diagram_dark.png` (or the `_light` version for bright
backgrounds). Point to each agent/station as you name it; the labelled connectors
(`text+type → policy facts → coverage → verdict → flags → .docx`) let you trace the
hand-off with your cursor.

**[SAY]**
> "Here's the pipeline. A document comes in through an MCP file server that validates
> it — by extension *and* magic bytes, so a virus renamed dot-pdf gets rejected at
> the door. Then six agents run in sequence, each one handing its structured output
> to the next:
>
> - **Agent 1, Ingestion** — reads the PDF or Word file and classifies its type.
>   Scanned documents fall back to Gemini vision, so there's no OCR dependency.
> - **Agent 2, Policy Extractor** — pulls the structured facts: premium, sum assured,
>   dates, and the maturity date.
> - **Agent 3, Coverage Analyzer** — separates what's covered from what's excluded,
>   plus waiting periods and sub-limits.
> - **Agent 4, Financial Evaluator** — this is the one with a real calculator tool.
>   It computes the effective annual return and benchmarks it against a fixed deposit
>   and an index fund, then returns a Profit, Break-even, or Net-loss verdict.
> - **Agent 5, Risk Flag** — surfaces the fine-print traps and rates each one, and
>   critically, tells standard boilerplate apart from genuinely unusual clauses.
> - **Agent 6, Report Composer** — assembles everything into a formatted,
>   plain-English Word document.
>
> Six agents built on Google's Agent Development Kit, with the calculator registered
> as an ADK tool. This is a genuine dependency chain, not parallel calls with a
> wrapper on top."

---

## 2:30 – 4:00 · Live demo  ⭐ (spend your best take here)

**[ON SCREEN]** Terminal, full-screen, large font. Run:
```
python scripts/demo_run.py sample_docs/sample_life_insurance_limited_pay.pdf
```
Let the six `▶ Agent N … ✓` lines appear one by one as they complete. When the
**AT A GLANCE** panel prints, pause on it. Then open the generated report:
`output/sample_life_insurance_limited_pay_insureiq_report.docx` in Word and scroll
through the sections.

**[SAY]** (while the agents run)
> "I'll run that same fourteen-page policy through the pipeline now. Watch the six
> agents fire in order — ingestion, extraction, coverage, financial, risk, report —
> each one printing what it found and how long it took."

**[SAY]** (on the AT A GLANCE panel — this is the payoff, slow down)
> "And here's the answer to those three questions from the start.
> **The maturity date** — pulled straight out of the fine print.
> **The financial verdict** — computed, not guessed: the effective annual return,
> side by side with a fixed deposit and an index fund, and a plain verdict on whether
> this policy actually beats just leaving the money in the bank.
> **And the red flags** — rated high, medium, low, with the genuinely unusual clauses
> called out separately from standard boilerplate."

**[SAY]** (opening the .docx)
> "All of that is also written up as a Word report you can hand to anyone — executive
> summary, the numbers, the coverage, and the flagged clauses, colour-coded by
> severity. The whole thing ran in about thirty seconds, and nothing touched disk —
> the document is processed entirely in memory."

> **Backup if quota is exhausted:** if the free-tier key is used up, the script prints
> a clean "⚠️ quota exhausted" message instead of a crash — mention that's expected,
> and cut to a pre-recorded successful run or the already-generated report in
> `output/`. Have one good run recorded *before* you shoot, as insurance.

---

## 4:00 – 5:00 · Tech stack & how it was built

**[ON SCREEN]** Quickly show, in order: the repo tree, `pipeline.py` (the 6 hand-offs),
one agent file, then the test run `pytest tests/ -q` finishing green (192 passed).

**[SAY]**
> "Under the hood: Python and FastAPI serving the API, Google's ADK orchestrating the
> six agents, Gemini 2.5 Flash as the model, an MCP server handling file intake, and
> python-docx generating the report.
>
> Two engineering decisions define the project. First, the **numbers-versus-prose
> split** — every figure a user sees is produced by deterministic Python; the model
> only writes narrative around it, so it literally cannot invent a return rate.
> Second, **it's testable without spending a cent** — the entire pipeline has a
> hundred-and-ninety-two-test suite that mocks the model, so a reviewer can verify all
> the agent logic offline, with no API key, in under a minute. [show green pytest run]
>
> It's containerized with Docker, port-aware for Cloud Run or Render, and every upload
> is validated and processed in memory. That's InsureIQ — six agents that turn an
> unreadable policy into a decision. Thanks for watching."

---

## Recording Checklist (run once before you shoot)

1. **Do a full dry run first.** `python scripts/demo_run.py sample_docs/sample_life_insurance_limited_pay.pdf`
   — confirm it completes and the AT A GLANCE panel looks good. **Record this run** so
   you have a guaranteed-good take even if quota runs out later.
2. **Terminal setup:** large font (≥16pt), dark theme, wide window. Windows Terminal
   renders the box-drawing and colours cleanly.
3. **Pre-generate the report** so opening it on camera is instant (the dry run does this).
4. **Confirm the tests are green** on camera: `pytest tests/ -q` → `192 passed`.
5. **Have the PDF already open** in a viewer for the 0:00 problem shot.
6. **Close notifications / other windows.** Full-screen everything.
7. **Audio:** record narration in a quiet room; you can also record silent and voice
   over in edit.

## What each rubric segment proves to a judge

| Segment | Course concept it demonstrates |
|---|---|
| Architecture (1:30) | Multi-agent system (ADK), MCP server, Agent Skills (ADK tool) |
| Live demo (2:30) | The system actually works end-to-end on a real document |
| Tech stack (4:00) | Security (in-memory, magic bytes), Deployability (Docker/$PORT), testing rigor |

You demonstrate **5 of the 6** course concepts genuinely (multi-agent/ADK, MCP,
ADK tools, security, deployability) — comfortably above the ≥3 required.
