---
description: Run the six-stage finance pipeline on a single stock (US or India) and produce a buy/hold/sell verdict.
argument-hint: <ticker-or-company-name> ["optional sector"]
allowed-tools: Bash(mkdir:*), Bash(date:*), Bash(ls:*), Bash(python3:*), Read, Write, Glob
---

# `/analyze-stock` — Orchestrator

You are running a **linear, file-backed finance pipeline** against a single stock.
Subject: **$ARGUMENTS**

The six analysis stages each write exactly one markdown report into the run's **analysis
folder**. The seventh stage synthesizes them into a single **final report** written to a
separate **output folder**. Later stages read earlier outputs from disk (filesystem handoff
— not context passing), so the run is auditable and re-runnable.

## Setup (do this first)

1. Parse `$ARGUMENTS`:
   - First token = **ticker or company name** (required). Uppercase a ticker; keep a
     company name as given. Call this `TICKER`.
   - Optional quoted second argument = **sector** (e.g. `"AI semiconductors"`). If absent,
     infer the sector during Step 4 and note that it was inferred.
   - If `$ARGUMENTS` is empty, stop and ask the user for a ticker or company name.
2. **Detect the market** and set `MARKET`, `EXCHANGE`, and `CURRENCY`. **India is the
   default** — only treat the stock as US when there's a clear US signal:
   - **US** only if any of: the symbol ends in a US suffix or is an unmistakably US-listed
     ticker (e.g. NVDA, AAPL, MSFT, TSLA); or the user said "US / NASDAQ / NYSE / S&P".
     → `MARKET=US`, `EXCHANGE=NASDAQ/NYSE`, `CURRENCY=USD ($)`.
   - **India** in every other case — including a bare symbol or company name with no market
     hint. → `MARKET=India`, `EXCHANGE=NSE` (or BSE if `.BO`), `CURRENCY=INR (₹)`. Normalize
     the symbol to its `.NS`/`.BO` form for any data lookup (default to `.NS` if no suffix is
     given), but use the **base symbol** (without suffix) for the folder name.
   - State the detected market when you announce the run. If a bare symbol genuinely exists
     in both markets and the intent is unclear, **default to India** but note the assumption
     so the user can correct it.
   - Use `MARKET`/`CURRENCY` consistently: every figure in every report is labelled in the
     right currency, and the India-specific source/macro guidance below applies when
     `MARKET=India`.
3. Compute today's date as `YYYY-MM-DD` (run `date +%F`). Call this `DATE` — used only to
   timestamp content *inside* the reports, never in folder names.
4. The run uses **one folder per stock, keyed by name only** (no date in the path), under the
   **stocks** namespace (mutual funds use the parallel `/analyze-fund` pipeline under
   `analysis/funds/` and `output/funds/`):
   - **Analysis folder:** `analysis/stocks/<TICKER>/` — holds the live-data file (`00`) and
     the six stage files (`01`–`06`).
   - **Output folder:** `output/stocks/<TICKER>/` — holds the final report (`07`) and the
     plain-English summary (`08`).
   Run `mkdir -p` on both (a no-op if they already exist).
5. **New stock vs. existing stock:**
   - If `analysis/stocks/<TICKER>/` did **not** already contain stage files, this is a fresh
     run — write all six files from scratch.
   - If it **did** already contain reports from a previous run, this is a **refresh**:
     overwrite each stage file in place with the new current data, and add a line near the
     top of every updated file — `> Last updated: <DATE>` — so the report reflects the
     latest run. Do not create a second dated folder; keep one living report per stock.
6. **Stage 0 — fetch live data (do this before Stage 1).** Run:

   ```
   python3 scripts/fetch_data.py <LOOKUP_SYMBOL> --outdir analysis/stocks/<TICKER>
   ```

   where `<LOOKUP_SYMBOL>` is the market-normalized symbol (India → `.NS`/`.BO`; US → bare).
   This writes `analysis/stocks/<TICKER>/00-market-data.md` (+ `.json` with full price
   history) — live quote, valuation, fundamentals, analyst consensus and technicals from
   Yahoo Finance.
   - If it exits non-zero because **yfinance is missing**, run
     `python3 -m pip install -r requirements.txt` once, then retry.
   - If it exits non-zero because the **symbol returned no data**, tell the user the symbol
     looks wrong (Indian tickers need `.NS`/`.BO`) and ask for the correct one before going on.
   - On success, **every later stage must treat `00-market-data.md` as the ground-truth data
     layer** — quote real figures from it, and flag anything that looks stale or inconsistent.
     This replaces the old "knowledge-based proxy" behavior.
7. Announce both folder paths, the detected market, and whether this is a fresh run or a
   refresh, then run the stages **in order**. Stages 1–6 write into the analysis folder;
   Stage 7 reads from the analysis folder and writes into the output folder.

## Plugin resolution & fallback

Each stage below names a plugin command (e.g. `/explore-data` from the `data` plugin).
Before a stage, check whether that command/plugin is available:

- **If available:** invoke it with the stage's trigger prompt and write its output to the
  stage file.
- **If NOT available:** do **not** fail. Perform the stage yourself as a finance analyst
  using the trigger prompt and the section schema given, clearly mark the file header with
  `> Generated by fallback (plugin '<name>' not installed).`, and continue.

A missing plugin weakens the chain but never blocks the run. Record every fallback in the
final report's caveats.

## Output style — every stage file (1–6) opens in plain English

Each of the six stage files must **begin with a plain-English block, right after the header
metadata and before the detailed sections:**

```
## In plain English
- <2–4 one-line, jargon-free bullets a non-technical reader can skim>
```

Rules for that block:
- **No jargon.** If a finance term is unavoidable, add a 3–4 word plain gloss in brackets.
- **One line per bullet**, 2–4 bullets, saying what this stage *found* and why it matters —
  not how it was done.
- The **detailed, analyst-grade sections still follow underneath** (tables, metrics, citations)
  — the synthesis stages (7, 8) rely on them. The plain block is a front door, not a
  replacement.

This mirrors the Stage 8 summary style, applied inline to each stage.

## India market guidance (applies when `MARKET=India`)

When the subject is an Indian stock, adapt every stage to the Indian market — do **not** use
US defaults:

- **Currency & units:** report all figures in **INR (₹)** and use Indian conventions
  (lakh / crore) where natural. Never silently mix USD and INR.
- **Symbols & exchanges:** trade on **NSE** (`.NS`) / **BSE** (`.BO`); benchmarks are the
  **Nifty 50** and **Sensex**, not the S&P 500.
- **Filings & disclosure:** regulator is **SEBI**; use NSE/BSE corporate announcements,
  exchange filings, and annual reports — **not** SEC/EDGAR. Quarterly results follow the
  Indian results calendar.
- **Preferred data sources for Stages 4–6** (sector research, equity research, scraper):
  **screener.in, NSE India, BSE India, moneycontrol, Tickertape, Trendlyne**, company
  investor-relations pages, and broker research. Stage 6's scraper should target these
  Indian sources for an Indian name.
- **Macro layer (Stages 4–5):** frame against **RBI** monetary policy (repo rate, inflation
  /CPI, INR exchange rate), Union Budget and GST effects, FII/DII flows, and India-specific
  sector dynamics — not the Fed.
- **Peers & valuation:** compare against **Indian sector peers** and Indian historical
  multiple ranges, not US peers.

For US names, keep the existing US framing (SEC/EDGAR, Fed, S&P, USD).

---

## Stage 1 — Explore Data → `01-data-exploration.md`
**Plugin:** `data` · **Command:** `/explore-data` · **Reads:** `00-market-data.md`

Discovery audit that runs *before* any analysis: is the data trustworthy enough to use?
Classify fields as metrics/dimensions/dates, profile against finance-grade quality checks
(missing values, duplicates, broken formatting, impossible negatives, missing identifiers),
surface the highest reporting-risk issues, and recommend fit-for-use.

**Trigger prompt:** *Analyze this raw enterprise sales and finance dataset. Identify hidden
patterns, anomalies, seasonality, customer segments, and operational insights. Then
summarize the most important discoveries for leadership.*

**File sections:** Leadership Summary (≤5 bullets, top of file) · Patterns · Anomalies ·
Seasonality · Customer Segments · Operational Insights · **Data Quality** (every integrity
issue + fit-for-use recommendation).

## Stage 2 — Validate Data → `02-data-validation.md`
**Plugin:** `data` · **Command:** `/validate-data` · **Reads:** `01`

Senior-reviewer audit of the *analysis itself*, not just the formulas. Check methodology →
right-question → calculations → anomaly detection across the dataset → narrative validation.
Critical issues are release-blocking. Read `01-data-exploration.md` first so the audit
targets the anomalies Step 1 flagged.

**Trigger prompt:** *Audit this financial reporting workbook for data integrity issues,
broken calculations, inconsistencies, duplicate records, impossible values, and audit risks.
Generate a validation summary with findings, written as a senior review.*

**File sections:** Findings table (issue · severity · location · recommended fix) ·
Anomaly Detection · Narrative Validation · **Sign-off** (Pass / Pass-with-caveats / Fail).

## Stage 3 — Variance Analysis → `03-variance-analysis.md`
**Plugin:** `finance` · **Command:** `/variance-analysis` · **Reads:** `01`, `02`

FP&A core: not whether numbers changed but *why* and *what to do*. Filter for materiality,
decompose revenue into price/volume/mix and payroll into headcount/timing, reconcile every
driver back to the reported number, build an EBITDA bridge. Build only on validated data
from Steps 1–2.

**Trigger prompt:** *Compare budget vs actual performance across regions, departments, and
product lines. Identify the main revenue and margin variance drivers. Generate an
executive-ready FP&A narrative.*

**File sections:** Variance Bridge (budget → actual, top drivers) · Per-Region /
Per-Department / Per-Product breakdowns · EBITDA Bridge · 60-second **FP&A Narrative** with
recommended actions.

## Stage 4 — Sector Research → `04-sector-research.md`
**Plugin:** `big data` · **Command:** `/financial-research-analyst` · **Reads:** —

First external stage. Route between company analysis vs macro/sector analysis and research
accordingly. Organize into the categories an institutional analyst cares about: growth
drivers, risks, valuation concerns. Place the subject stock within its sector.

**Trigger prompt:** *Create a full research brief on the [sector of $ARGUMENTS]: leading
companies, valuation trends, macro risks, earnings momentum, and the key themes shaping the
market.*

**File sections:** Leading Companies · Valuation Trends · Macro Risks · Earnings Momentum ·
Key Themes · Market Sizing · Investment Implications · Where the subject stock sits.

## Stage 5 — Equity Research → `05-equity-research.md`
**Plugin:** `LSEG` · **Command:** `/equity-research` · **Reads:** `04`, `00-market-data.md`

Single-name institutional view. Consensus + estimate dispersion → fundamentals (growth,
profitability, balance-sheet quality) → market positioning → macro layer → synthesis
(does valuation match growth quality; are expectations stretched?). Frame against the sector
from Step 4.

**Trigger prompt:** *Generate an institutional-style equity research snapshot for
$ARGUMENTS: consensus estimates, valuation analysis, historical performance, macro context,
a bull/bear thesis, and an investment outlook.*

**File sections:** Company Profile · Consensus & Estimate Dispersion · Fundamentals ·
Valuation vs Peers/History · Market Positioning · Macro Context · **Bull Case / Bear Case**
(side-by-side) with catalysts and a risk-reward read.

## Stage 6 — Scraper Builder → `06-scraper-build.md`
**Plugin:** `Bright Data` · **Command:** `/scraper-builder` · **Reads:** —

Design a financial-intelligence scraper that turns external sites into a continuously
updating dataset (competitor pricing, product launches, market signals). Study each site
first, choose the most stable extraction method per site, structure into business fields
with provenance, scale pagination. In this pipeline, **design and document** the scraper and
surface any signals relevant to the subject stock.

**Trigger prompt:** *Build a production-ready financial intelligence scraper that collects
competitor pricing, product launches, and market signals from multiple websites, then
structures the output into a clean, analytics-ready dataset.*

**File sections:** Scraper Design · Target Sites · Extraction Method per site · Output Schema
(columns · types · provenance) · Signals relevant to the subject stock.

## Stage 7 — Final Verdict → `output/stocks/<TICKER>/07-final-recommendation.md`
**Plugin:** none — pure synthesis. **Reads:** `01`–`06` from the analysis folder.

Read all six stage files from the analysis folder and **synthesize, do not re-derive**.
Write the final report into the **output folder** (not the analysis folder), with exactly
these sections:

1. **Verdict:** BUY / HOLD / SELL — one line, plainly stated.
2. **Conviction:** High / Medium / Low, with reasoning.
3. **Entry guidance:** at what price or condition it becomes a buy, and the level that
   invalidates the thesis.
4. **The case in 3 bullets:** strongest evidence from Steps 1–6, each citing its source file.
5. **Key risks:** the 3 things most likely to break the thesis.
6. **What to watch next:** catalysts or data points that would move the verdict.
7. **Closing line:** this is automated analysis, not personal financial advice; confirm the
   underlying numbers before acting. List any stages that ran in fallback mode.

## Stage 8 — Plain-English Summary → `output/stocks/<TICKER>/08-summary.md`
**Plugin:** none — pure summarization. **Reads:** `07-final-recommendation.md`.

Read the final report and write a **short, plain-English TL;DR for a non-technical reader.**
This is the file someone opens first — it must be skimmable in 30 seconds.

Rules:
- **No jargon.** If a finance term is unavoidable, add a 3–4 word plain gloss in brackets.
- **One line per point.** No paragraphs, no tables, no source-file citations.
- Keep the whole file to **roughly 12–15 lines.** Shorter is better.
- Plain language a parent or friend could follow; spell out what the numbers *mean*, not just
  what they are (e.g. "trading 18% below its recent high — cheaper than it was").

Structure (use these exact headings):
```
# <Company> (<TICKER>) — Quick Summary

**Bottom line:** <BUY/HOLD/SELL> — <one plain sentence on what that means to do>.
**How confident:** <High/Medium/Low> — <one plain reason>.
**Price now:** <₹/$ price> (<one phrase of context, e.g. near its 1-year low>).

## In plain English
- <main point 1, one line>
- <main point 2>
- <main point 3>
- <main point 4>
- <main point 5>  (aim for 4–6 bullets total)

## If you're considering it
- **Could buy around:** <level/condition, plain>.
- **Walk away if:** <the one thing that breaks the case, plain>.
- **Watch for:** <the single biggest thing that would change the answer>.

_Automated analysis, not financial advice. Numbers as of <DATE>; double-check before acting._
```

After writing it, this summary — not the long report — is what you point the user to first.

---

## Finish

Print to the terminal (without requiring the user to open a file):
- the **Verdict** and **Conviction**,
- the **plain-English summary path** (`output/stocks/<TICKER>/08-summary.md`) — point the
  user here first,
- the **analysis folder path** (stage files) and the **output folder path** (full report + summary),
- a one-line list of any stages that ran in fallback mode.
