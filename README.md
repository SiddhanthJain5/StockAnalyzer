# Stock Analysis Pipeline

A file-backed finance pipeline, driven by a single Claude Code slash command, that takes a
stock name as input and runs it through six analysis stages before producing a
**buy / hold / sell** verdict.

## Usage

```
/analyze-stock TICKER
/analyze-stock TICKER "sector"        # optionally pin the sector
/analyze-stock "Company Name"

# India (default) — a bare symbol or Indian name resolves to NSE
/analyze-stock RELIANCE
/analyze-stock TCS.NS "IT services"
/analyze-stock "HDFC Bank"
# US — needs a clear US signal (US ticker, or "US/NASDAQ/NYSE")
/analyze-stock NVDA
```

## Markets: India (default) & US

The command **auto-detects the market, defaulting to India**. A bare symbol or company name
with no market hint resolves to **NSE** (`.NS`). The run switches to **US** mode only on a
clear US signal — an unmistakable US ticker (NVDA, AAPL…) or words like "US / NASDAQ / NYSE".

| | India (default) | US |
|--|-----------------|----|
| Exchanges | NSE (`.NS`) / BSE (`.BO`) | NASDAQ / NYSE |
| Currency  | INR (₹), lakh/crore | USD ($) |
| Benchmarks | Nifty 50, Sensex | S&P 500 |
| Filings | SEBI, NSE/BSE announcements | SEC / EDGAR |
| Macro | RBI, Union Budget, GST, FII/DII flows | Fed |
| Sources (Stages 4–6) | screener.in, NSE/BSE, moneycontrol, Tickertape, Trendlyne | global desks |

All figures are labelled in the detected currency, and the India sources/macro framing kick
in automatically — no separate command needed.

Each run writes two folders, **one per stock, keyed by name only** (no date in the path):
- `analysis/<TICKER>/` — the **six analysis stage files** (`01`–`06`).
- `output/<TICKER>/` — the **final report** (`07-final-recommendation.md`).

Re-running the same stock **updates the existing reports in place** with current data (each
file carries a `Last updated:` line) instead of creating a new folder — one living report per
stock. The verdict, conviction, and both folder paths are printed to the terminal at the end.

## Setup

The pipeline fetches live market data via [`yfinance`](https://pypi.org/project/yfinance/).
Install it once:

```
python3 -m pip install -r requirements.txt
```

`yfinance` covers **Indian stocks** through Yahoo Finance: use the NSE suffix `.NS`
(`RELIANCE.NS`) or BSE suffix `.BO` (`RELIANCE.BO`); prices come back in ₹ INR. US tickers are
passed bare (`NVDA`). The command runs the fetch automatically (Stage 0) and will offer to
install the dependency if it's missing.

For Indian tickers, Stage 0 also scrapes **[screener.in](https://www.screener.in)** to add
what Yahoo lacks: a quarterly **OPM/EPS** trend, **ROCE**, compounded sales/profit growth, and
the site's **Pros/Cons** read. (Screener exposes consolidated fundamentals, not a business-
segment split — Jio/Retail/O2C lines live in annual-report notes.) The scrape degrades
gracefully: US tickers skip it, and any network/parse failure is recorded without breaking the
run.

## The pipeline

The command moves **inside-out** — from raw data trustworthiness, to internal performance,
to external sector and single-name research, to live signals, then collapses everything into
a decision:

| # | Stage | Plugin | Command | Output | Folder |
|---|-------|--------|---------|--------|--------|
| 0 | Live Data Fetch    | —          | `scripts/fetch_data.py`       | `00-market-data.md` + `.json` | `analysis/` |
| 1 | Data Exploration   | data       | `/explore-data`               | `01-data-exploration.md`    | `analysis/` |
| 2 | Data Validation    | data       | `/validate-data`              | `02-data-validation.md`     | `analysis/` |
| 3 | Variance Analysis  | finance    | `/variance-analysis`          | `03-variance-analysis.md`   | `analysis/` |
| 4 | Sector Research    | big data   | `/financial-research-analyst` | `04-sector-research.md`     | `analysis/` |
| 5 | Equity Research    | LSEG       | `/equity-research`            | `05-equity-research.md`     | `analysis/` |
| 6 | Intelligence Scraper | Bright Data | `/scraper-builder`          | `06-scraper-build.md`       | `analysis/` |
| 7 | Final Verdict      | —          | (synthesis)                   | `07-final-recommendation.md`| `output/` |
| 8 | Plain-English Summary | —       | (summarization)               | `08-summary.md`             | `output/` |

**Dependencies:** `1 → 2 → 3` build on validated data; `4 → 5` frames the single name against
its sector; Steps 4 and 6 have no upstream dependency; everything funnels into Step 7.

## Plugins

The stages 1–6 call external plugin commands (`data`, `finance`, `big data`, `LSEG`,
`Bright Data`). If a plugin is not installed, that stage runs in **fallback mode** — Claude
performs the analysis itself, marks the file, and continues. Every fallback is recorded in
the final report. Confirm installed plugins by typing `/` in Claude Code.

> **Note on scope.** Steps 1–3 (and the scraper in Step 6) were designed around *private*
> operational data — enterprise workbooks, budget-vs-actual files, competitor pricing. For a
> public listed name you usually won't have an internal workbook, so Steps 4, 5, and 7 are
> the load-bearing stages. Repoint 1–3 at public filings if you're screening public stocks.

## Layout

```
.
├── .claude/commands/analyze-stock.md   # the orchestrator command
├── scripts/fetch_data.py               # Stage 0: live data via yfinance
├── requirements.txt                    # yfinance
├── analysis/                           # Stage 0 data + six stage files per run (git-ignored)
│   └── README.md
├── output/                             # final report per run (git-ignored per-run)
│   └── README.md
├── .gitignore
└── README.md
```

## Disclaimer

Output is automated analysis, not personal financial advice. Confirm the underlying numbers
before acting.

---

Full design spec: `stock-analyzer-spec.md` (kept in Downloads).
