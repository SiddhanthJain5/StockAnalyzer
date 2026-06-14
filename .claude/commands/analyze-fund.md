---
description: Run the mutual-fund analysis pipeline (India, AMFI/mfapi.in NAV data) and produce a SIP/switch/exit verdict.
argument-hint: <fund-name-or-amfi-scheme-code> ["Direct"/"Regular" "Growth"/"IDCW" if the name is ambiguous]
allowed-tools: Bash(mkdir:*), Bash(date:*), Bash(ls:*), Bash(rm:*), Bash(python3:*), Read, Write, Glob
---

# `/analyze-fund` — Orchestrator

You are running a **linear, file-backed fund-analysis pipeline** against a single Indian
mutual fund scheme.
Subject: **$ARGUMENTS**

This mirrors `/analyze-stock` but is adapted for mutual funds: NAV-based performance instead
of price/valuation, category/benchmark comparison instead of sector peers, and a
SIP/switch/exit verdict instead of BUY/HOLD/SELL. The six analysis stages each write exactly
one markdown report into the run's **analysis folder**. The seventh stage synthesizes them
into a **final report**, and the eighth writes a plain-English summary — both in a separate
**output folder**. Later stages read earlier outputs from disk (filesystem handoff — not
context passing), so the run is auditable and re-runnable.

This pipeline is **India-only** (mfapi.in serves AMFI-registered Indian mutual fund schemes).
All figures are in **INR (₹)**.

## Setup (do this first)

1. Parse `$ARGUMENTS`:
   - If it's purely numeric, treat it as an **AMFI scheme code** (`SCHEME_CODE`).
   - Otherwise it's a **fund-name query** (`FUND_QUERY`) — e.g. "Parag Parikh Flexi Cap
     Direct Growth", "HDFC Mid-Cap Opportunities". Including the plan (Direct/Regular) and
     option (Growth/IDCW) helps avoid ambiguous matches later.
   - If `$ARGUMENTS` is empty, stop and ask the user for a fund name or AMFI scheme code.
2. **Derive `FUND_NAME`** — the folder key (uppercase, snake-case):
   - If `FUND_QUERY` is set: uppercase it, drop the filler words `FUND`, `SCHEME`, `PLAN`,
     `DIRECT`, `REGULAR`, `GROWTH`, `IDCW`, `DIVIDEND`, `MUTUAL`, `OPTION` (whole words only),
     then collapse remaining whitespace/punctuation into single underscores and trim
     leading/trailing underscores. E.g. "Parag Parikh Flexi Cap Direct Growth" →
     `PARAG_PARIKH_FLEXI_CAP`. If nothing is left after stripping, fall back to the
     uppercased, underscored original query.
   - If `SCHEME_CODE` is set instead: `FUND_NAME = SCHEME_CODE` (e.g. `122639`) — you don't
     know the human-readable name yet, and that's fine.
3. Compute today's date as `YYYY-MM-DD` (run `date +%F`). Call this `DATE` — used only to
   timestamp content *inside* the reports, never in folder names.
4. The run uses **one folder per fund, keyed by `FUND_NAME` only** (no date in the path),
   under the **funds** namespace (stocks use the parallel `/analyze-stock` pipeline under
   `analysis/stocks/` and `output/stocks/`):
   - **Analysis folder:** `analysis/funds/<FUND_NAME>/` — holds the live-data file (`00`)
     and the six stage files (`01`–`06`).
   - **Output folder:** `output/funds/<FUND_NAME>/` — holds the final report (`07`) and the
     plain-English summary (`08`).
   Run `mkdir -p` on both (a no-op if they already exist).
5. **New fund vs. existing fund:**
   - If `analysis/funds/<FUND_NAME>/` did **not** already contain stage files, this is a
     fresh run — write all six files from scratch.
   - If it **did** already contain reports from a previous run, this is a **refresh**:
     overwrite each stage file in place with the new current data, and add a line near the
     top of every updated file — `> Last updated: <DATE>` — so the report reflects the
     latest run. Do not create a second folder; keep one living report per fund.
6. **Stage 0 — fetch live NAV data (do this before Stage 1).** Run:

   ```
   python3 scripts/fetch_fund_data.py "<FUND_QUERY>" --outdir analysis/funds/<FUND_NAME>
   ```
   or, if `$ARGUMENTS` was a scheme code:
   ```
   python3 scripts/fetch_fund_data.py <SCHEME_CODE> --outdir analysis/funds/<FUND_NAME> --scheme-code
   ```

   This writes `analysis/funds/<FUND_NAME>/00-fund-data.md` (+ `.json` with full NAV history)
   — latest NAV, trailing CAGR (1y/3y/5y/10y/since inception), 1-year volatility, and max
   drawdown, all computed from AMFI NAV history via mfapi.in.

   Handle the exit code:
   - **0** — success, proceed to Stage 1.
   - **2** — `requests` is missing: run `python3 -m pip install -r requirements.txt` once,
     then retry.
   - **3** — no scheme matched, or the fetch failed: tell the user the name looks wrong and
     ask for a more specific name (fund house + category) or the AMFI scheme code.
   - **4** — **ambiguous name**: the script wrote `analysis/funds/<FUND_NAME>/candidates.json`
     listing every matching scheme (Direct vs Regular, Growth vs IDCW, etc.). Read it, list
     the candidates to the user with their scheme codes and full names, and ask which one
     they mean. If the user has no preference, **recommend the Direct Plan + Growth option**
     (lowest cost, no payouts) as the default, confirm with the user, then re-run:
     ```
     python3 scripts/fetch_fund_data.py <CHOSEN_SCHEME_CODE> --outdir analysis/funds/<FUND_NAME> --scheme-code
     ```
     Once it succeeds, delete `candidates.json` (it was only a handoff artifact). If the
     resolved `scheme_name` in `00-fund-data.json` suggests a clearer `FUND_NAME`, you may
     re-derive it and `mv` the folder — otherwise keep the current `FUND_NAME`.
   - On success, **every later stage must treat `00-fund-data.md` as the ground-truth data
     layer** — quote real NAV/CAGR/risk figures from it, and flag anything that looks stale
     or inconsistent.
7. Announce both folder paths, the resolved fund name, and whether this is a fresh run or a
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
- The **detailed, analyst-grade sections still follow underneath** (tables, metrics,
  citations) — the synthesis stages (7, 8) rely on them. The plain block is a front door, not
  a replacement.

This mirrors the Stage 8 summary style, applied inline to each stage.

## Mutual fund context (India)

Every fund analyzed by this pipeline is an **AMFI-registered Indian mutual fund scheme**
(SEBI-regulated). Apply these conventions throughout:

- **Currency & units:** report all figures in **INR (₹)**; use lakh/crore for AUM where
  natural.
- **Regulator & filings:** **SEBI** regulates mutual funds; **AMFI** publishes the daily NAVs
  that back `00-fund-data.md`. Scheme Information Documents (SIDs) and monthly factsheets are
  the primary disclosure documents — not SEC/EDGAR or company annual reports.
- **Benchmarks:** compare against the fund's **stated benchmark index** (e.g. Nifty 50 TRI,
  Nifty 500 TRI, Nifty Midcap 150 TRI) and its **Morningstar/Value Research category
  average** — not the S&P 500 or US fund categories.
- **Preferred data sources for Stages 4–6** (category research, fund research, scraper):
  **Value Research, moneycontrol, Morningstar India, Tickertape, AMC factsheet pages, AMFI**.
  `00-fund-data.md` (mfapi.in) covers NAV / CAGR / volatility / drawdown only — it has **no
  expense ratio, AUM, portfolio holdings, exit load, or benchmark return**, so Stages 4–6
  must source those from the sites above and flag clearly when a figure is unavailable.
- **Macro layer (Stage 4):** frame against **RBI** monetary policy, the equity market cycle
  (Nifty/Sensex levels and valuations), and flows into the fund's category — not the Fed.
- **Costs:** **expense ratio** and **exit load** materially affect long-term returns —
  surface them whenever available and flag clearly if they're unavailable.

---

## Stage 1 — Explore Data → `01-data-exploration.md`
**Plugin:** `data` · **Command:** `/explore-data` · **Reads:** `00-fund-data.md`

Discovery audit that runs *before* any analysis: is the data trustworthy enough to use?
Profile the NAV history and computed return/risk figures, surface the highest reporting-risk
issues, and recommend fit-for-use.

**Trigger prompt:** *Analyze this mutual fund's NAV history and computed return/risk metrics.
Identify the growth trajectory, drawdown periods, volatility regime changes, and any
data-quality issues. Summarize the most important discoveries for someone deciding whether to
keep investing.*

**File sections:** Leadership Summary (≤5 bullets, top of file) · NAV & Return Trajectory
(growth phases, CAGR by period) · Drawdowns & Volatility Regimes · Seasonality (note if none
material) · Category/Plan Context (what this scheme is — Direct/Regular, Growth/IDCW,
category) · Operational Insights (inception date, history length, data completeness) ·
**Data Quality** (gaps/staleness in the NAV series + fit-for-use recommendation).

## Stage 2 — Validate Data → `02-data-validation.md`
**Plugin:** `data` · **Command:** `/validate-data` · **Reads:** `01`

Senior-reviewer audit of the *analysis itself*, not just the formulas. Check that the CAGR
windows, volatility, and max-drawdown figures are calculated and interpreted correctly, and
that Stage 1's conclusions are actually supported by the data. Read
`01-data-exploration.md` first so the audit targets the issues Step 1 flagged.

**Trigger prompt:** *Audit this mutual fund's NAV-derived return and risk calculations (CAGR
windows, volatility, max drawdown) for correctness, consistency, and any conclusions in Stage
1 that aren't supported by the data. Generate a validation summary written as a senior
review.*

**File sections:** Findings table (issue · severity · location · recommended fix) ·
Anomaly Detection · Narrative Validation · **Sign-off** (Pass / Pass-with-caveats / Fail).

## Stage 3 — Performance vs Benchmark/Category → `03-performance-variance.md`
**Plugin:** `finance` · **Command:** `/variance-analysis` · **Reads:** `01`, `02`,
`00-fund-data.md`

Not whether the fund's returns moved but *why*, relative to what an investor's money would
have done elsewhere. Compare trailing CAGR (1Y/3Y/5Y/10Y/since inception) against the stated
benchmark index and the category average, decompose the gap into market-driven (beta) vs
manager-driven (alpha), and reconcile each period back to the reported CAGR. Build only on
validated data from Steps 1–2.

**Trigger prompt:** *Compare this fund's trailing returns (1Y/3Y/5Y/10Y/since inception)
against its stated benchmark index and its Morningstar/Value Research category average.
Identify which periods the fund out- or under-performed, and whether that's market-driven
(beta) or manager-driven (alpha). Build a return bridge and a 60-second narrative with what
it implies for an existing investor.*

**File sections:** Return Bridge (benchmark return → category average → fund return, per
period) · Per-Period Breakdown (1Y/3Y/5Y/10Y/since inception table) · Alpha/Beta Read
(manager skill vs market) · 60-second **Narrative** with implications for SIP/lumpsum
investors.

## Stage 4 — Category Research → `04-category-research.md`
**Plugin:** `big data` · **Command:** `/financial-research-analyst` · **Reads:** —

First external stage. Research the fund's **category** (e.g. Flexi Cap, Large Cap, Mid Cap,
ELSS) the way an institutional analyst would: leading funds, AUM/flow trends, cost
benchmarks, macro risks. Place the subject fund within its category.

**Trigger prompt:** *Create a full research brief on the [category of the fund] in India:
leading funds in the category, AUM and flow trends, expense ratio ranges, macro risks (RBI
policy, market valuation), and the key themes shaping the category.*

**File sections:** Leading Funds in Category · AUM & Flow Trends · Expense Ratio Ranges ·
Macro Risks · Key Themes · Category Sizing · Investment Implications · Where the subject fund
sits.

## Stage 5 — Fund Research → `05-fund-research.md`
**Plugin:** `LSEG` · **Command:** `/equity-research` · **Reads:** `04`, `00-fund-data.md`

Single-scheme institutional view. Manager and mandate → portfolio composition (if available)
→ risk-adjusted performance vs benchmark/category → costs → synthesis (is the fund earning
its fees; is performance manager skill or just market beta?). Frame against the category from
Step 4.

**Trigger prompt:** *Generate an institutional-style fund research snapshot for [fund name]:
fund manager and strategy/mandate, portfolio composition if available (top holdings,
sector/market-cap allocation), risk-adjusted performance vs benchmark and category, expense
ratio and costs, and a bull/bear case for an existing or prospective investor.*

**File sections:** Fund Profile · Manager & Strategy/Mandate · Portfolio Composition (if
available — else flagged as a Stage 6 data gap) · Risk-Adjusted Performance vs
Benchmark/Category · Expense Ratio & Costs · Peer Comparison · **Bull Case / Bear Case**
(side-by-side) with catalysts and a risk-reward read.

## Stage 6 — Scraper Builder → `06-scraper-build.md`
**Plugin:** `Bright Data` · **Command:** `/scraper-builder` · **Reads:** —

Design a financial-intelligence scraper that fills the gaps `00-fund-data.md` cannot: expense
ratio, exit load, AUM, portfolio holdings/sector allocation, fund manager, and benchmark
returns. Study each site first, choose the most stable extraction method per site, structure
into business fields with provenance.

**Trigger prompt:** *Build a production-ready scraper that collects expense ratio, exit load,
AUM, portfolio holdings/sector allocation, fund manager, and benchmark returns from Value
Research, moneycontrol, Morningstar India, and AMC factsheet pages, then structures the
output into a clean, analytics-ready dataset.*

**File sections:** Scraper Design · Target Sites · Extraction Method per site · Output Schema
(columns · types · provenance) · Signals relevant to the subject fund.

## Stage 7 — Final Verdict → `output/funds/<FUND_NAME>/07-final-recommendation.md`
**Plugin:** none — pure synthesis. **Reads:** `01`–`06` from the analysis folder.

Read all six stage files from the analysis folder and **synthesize, do not re-derive**.
Write the final report into the **output folder** (not the analysis folder), with exactly
these sections:

1. **Verdict:** one of **Continue/Start SIP**, **Hold — No Fresh Investment**, **Switch to
   Alternative**, or **Exit/Redeem** — one line, plainly stated.
2. **Conviction:** High / Medium / Low, with reasoning.
3. **Investment guidance:** SIP vs lumpsum recommendation for this fund right now, and the
   condition or threshold that would invalidate the thesis (e.g. sustained underperformance
   vs category for several quarters, manager exit, a sharp expense-ratio hike).
4. **The case in 3 bullets:** strongest evidence from Steps 1–6, each citing its source file.
5. **Key risks:** the 3 things most likely to break the thesis.
6. **What to watch next:** catalysts or data points that would move the verdict.
7. **Closing line:** this is automated analysis, not personal financial advice; confirm the
   underlying numbers before acting. List any stages that ran in fallback mode.

## Stage 8 — Plain-English Summary → `output/funds/<FUND_NAME>/08-summary.md`
**Plugin:** none — pure summarization. **Reads:** `01`–`06` from the analysis folder and
`07-final-recommendation.md` from the output folder.

Read the final report **and** all six stage files, then write a **short, plain-English
TL;DR for a non-technical reader.** This is the file someone opens first — it must be
skimmable in 30 seconds, but it must also surface the *non-obvious* findings the six-stage
analysis actually produced. Use `07` for the verdict, conviction, and investment guidance;
use `01`–`06` to mine for the findings described below.

### Surface facts vs. analysis findings

A **surface fact** is anything visible on any fund-tracker app or factsheet within 5
seconds — current NAV, category (e.g. Flexi Cap), 1Y/3Y/5Y return, expense ratio as a bare
number, AUM, "beat its benchmark last year." These are fine for orientation but carry almost
no information about what the six-stage analysis added.

An **analysis finding** is something that required reading multiple stages and connecting
them — it changes what a surface fact *means*, or surfaces something a 5-second look would
miss entirely. Generalizable examples (not fund-specific — calibrate to whatever the run
actually found):
- **An anomaly plus its explained/unexplained status.** Not "1-year return is down X%"
  (surface), but "that weak 1-year number is mostly explained by one bad stretch tied to a
  sector the fund was overweight — whether that's a one-off or a pattern depends on whether
  the manager has changed positioning since (open question)."
- **A contradiction between two data sources that shouldn't be combined.** Not "the fund
  returned X%" (picking one source silently), but "the NAV-derived return and the
  factsheet's stated return differ because they cover slightly different windows — don't
  treat them as the same number."
- **A category-relative or own-history reframe that changes what a number means.** Not
  "beat its benchmark over 5 years" (surface), but "most of that outperformance happened in
  one earlier stretch — over the last 1-2 years it has tracked the category average almost
  exactly, so the long-run number overstates *recent* manager skill."
- **A structural risk surfaced by cross-referencing two unrelated data points.** Not "the
  fund has a high expense ratio" (surface-ish), but "combine the expense ratio with how
  closely its recent returns track the category average, and the fund is increasingly just
  charging active-management fees for what's become close to index-like performance."
- **A validation note that changes how alarming a number should feel.** Not just relaying a
  scary drawdown figure, but "we checked — that drawdown lines up with a broad market-wide
  correction, not something fund-specific, so it says more about the market than about this
  fund's risk management."

### Rules

- **No jargon.** If a finance term is unavoidable, add a 3–4 word plain gloss in brackets.
- **One line per point.** No paragraphs, no tables, no source-file citations.
- Keep the whole file to **roughly 18–24 lines.** The "Beyond the headline numbers" section
  is the point of this file — don't sacrifice it to hit a shorter number, but don't pad
  either.
- Plain language a parent or friend could follow; spell out what the numbers *mean*, not just
  what they are (e.g. "grown about 15% a year on average since 2013 — turns ₹1 lakh into
  roughly ₹6 lakh").
- **Lead with insight, not restatement.** `## In plain English` should orient the reader
  (what kind of fund this is, and the bottom-line call) — it is **not** a second list of
  return figures. Cap it at **one** surface-fact bullet.
- **`## Beyond the headline numbers` is the core deliverable of this file.** Pull
  **3–5 analysis findings**, each one **contrasting "the obvious read" with "what we found"**
  in a single line. Cite findings by stage number in parentheses so a curious reader can dig
  in, e.g. `(Stage 3)`.

Structure (use these exact headings):
```
# <Fund Name> — Quick Summary

**Bottom line:** <Verdict> — <one plain sentence on what that means to do>.
**How confident:** <High/Medium/Low> — <one plain reason>.
**NAV now:** ₹<NAV> (<one phrase of context, e.g. up about 15%/year on average over 5 years>).

## In plain English
- <what kind of fund this is and the overall shape of the situation, one line>
- <at most ONE surface-fact bullet, with plain context>
- <one line setting up why "Beyond the headline numbers" below is worth reading>

## Beyond the headline numbers
- <analysis finding 1 — "looks like X, but we found Y" framing> (Stage N)
- <analysis finding 2> (Stage N)
- <analysis finding 3> (Stage N)
- <analysis finding 4, optional> (Stage N)
- <analysis finding 5, optional> (Stage N)

## If you're considering it
- **Investment mode:** <SIP / lumpsum guidance, plain>.
- **Walk away if:** <the one thing that breaks the case, plain>.
- **Watch for:** <the single biggest thing that would change the answer>.

_Automated analysis, not financial advice. Numbers as of <DATE>; double-check before acting._
```

### Edge cases

- **A stage ran in fallback mode but still has rich content:** fallback mode alone is not a
  reason to skip a stage's findings — judge by content, not by mode.
- **A stage's content is genuinely thin or templated:** don't force an insight from it —
  pull from the other stages instead. If across all six stages you truly can't find at
  least **2** genuine findings, say so plainly (e.g. "Nothing in this run contradicted the
  obvious read — the headline numbers and the deeper analysis agree.") rather than
  manufacturing one.
- **Do not pad** "Beyond the headline numbers" with a restated surface fact just to hit 3
  bullets — quality and genuine non-obviousness over count.

After writing it, this summary — not the long report — is what you point the user to first.

---

## Finish

Print to the terminal (without requiring the user to open a file):
- the **Verdict** and **Conviction**,
- the **plain-English summary path** (`output/funds/<FUND_NAME>/08-summary.md`) — point the
  user here first,
- the **analysis folder path** (stage files) and the **output folder path** (full report +
  summary),
- a one-line list of any stages that ran in fallback mode.
