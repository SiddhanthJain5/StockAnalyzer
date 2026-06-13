# Stock & Mutual Fund Analysis Pipelines

Two file-backed finance pipelines, each driven by a single Claude Code slash command:

- **`/analyze-stock`** — takes a stock name/ticker (US or India), runs it through six
  analysis stages, and produces a **buy / hold / sell** verdict.
- **`/analyze-fund`** — takes an Indian mutual fund name or AMFI scheme code, runs the same
  six-stage shape adapted for funds, and produces a **Continue/Start SIP · Hold · Switch ·
  Exit** verdict.

Both pipelines write **one folder per subject, keyed by name only** (no date in the path),
under `analysis/{stocks,funds}/` and `output/{stocks,funds}/`. Re-running the same subject
**updates the existing reports in place** with current data (each file carries a
`Last updated:` line) instead of creating a new folder — one living report per
stock/fund. In each case, the verdict, conviction, and both folder paths are printed to the
terminal at the end of the run.

---

## `/analyze-stock`

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

### Markets: India (default) & US

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

Each run writes two folders, **one per stock, keyed by name only**:
- `analysis/stocks/<TICKER>/` — live data (`00`) + the **six analysis stage files** (`01`–`06`).
- `output/stocks/<TICKER>/` — the **final report** (`07`) + **plain-English summary** (`08`).

### The pipeline

The command moves **inside-out** — from raw data trustworthiness, to internal performance,
to external sector and single-name research, to live signals, then collapses everything into
a decision:

| # | Stage | Plugin | Command | Output | Folder |
|---|-------|--------|---------|--------|--------|
| 0 | Live Data Fetch    | —          | `scripts/fetch_data.py`       | `00-market-data.md` + `.json` | `analysis/stocks/` |
| 1 | Data Exploration   | data       | `/explore-data`               | `01-data-exploration.md`    | `analysis/stocks/` |
| 2 | Data Validation    | data       | `/validate-data`              | `02-data-validation.md`     | `analysis/stocks/` |
| 3 | Variance Analysis  | finance    | `/variance-analysis`          | `03-variance-analysis.md`   | `analysis/stocks/` |
| 4 | Sector Research    | big data   | `/financial-research-analyst` | `04-sector-research.md`     | `analysis/stocks/` |
| 5 | Equity Research    | LSEG       | `/equity-research`            | `05-equity-research.md`     | `analysis/stocks/` |
| 6 | Intelligence Scraper | Bright Data | `/scraper-builder`          | `06-scraper-build.md`       | `analysis/stocks/` |
| 7 | Final Verdict      | —          | (synthesis)                   | `07-final-recommendation.md`| `output/stocks/` |
| 8 | Plain-English Summary | —       | (summarization)               | `08-summary.md`             | `output/stocks/` |

**Dependencies:** `1 → 2 → 3` build on validated data; `4 → 5` frames the single name against
its sector; Steps 4 and 6 have no upstream dependency; everything funnels into Step 7.

> **Note on scope.** Steps 1–3 (and the scraper in Step 6) were designed around *private*
> operational data — enterprise workbooks, budget-vs-actual files, competitor pricing. For a
> public listed name you usually won't have an internal workbook, so Steps 4, 5, and 7 are
> the load-bearing stages. Repoint 1–3 at public filings if you're screening public stocks.

For Indian tickers, Stage 0 also scrapes **[screener.in](https://www.screener.in)** to add
what Yahoo lacks: a quarterly **OPM/EPS** trend, **ROCE**, compounded sales/profit growth, and
the site's **Pros/Cons** read. (Screener exposes consolidated fundamentals, not a business-
segment split — Jio/Retail/O2C lines live in annual-report notes.) The scrape degrades
gracefully: US tickers skip it, and any network/parse failure is recorded without breaking the
run.

---

## `/analyze-fund`

```
/analyze-fund "Parag Parikh Flexi Cap Direct Growth"
/analyze-fund "HDFC Mid-Cap Opportunities Fund"
/analyze-fund 122639                  # AMFI scheme code, if you know it
```

**India-only** — every fund is an AMFI-registered scheme (SEBI-regulated), and all figures
are in **INR (₹)**. If a fund name matches multiple schemes (Direct vs Regular, Growth vs
IDCW), the command lists the candidates and asks which one you mean — including the plan and
option in your query (as in the first example above) avoids this.

Each run writes two folders, **one per fund, keyed by name only**:
- `analysis/funds/<FUND_NAME>/` — live NAV data (`00`) + the **six analysis stage files**
  (`01`–`06`).
- `output/funds/<FUND_NAME>/` — the **final report** (`07`) + **plain-English summary** (`08`).

### The pipeline

Same shape as `/analyze-stock`, adapted for funds: NAV-based performance instead of
price/valuation, category/benchmark comparison instead of sector peers, and a SIP/switch/exit
verdict instead of BUY/HOLD/SELL.

| # | Stage | Plugin | Command | Output | Folder |
|---|-------|--------|---------|--------|--------|
| 0 | Live NAV Fetch | — | `scripts/fetch_fund_data.py` | `00-fund-data.md` + `.json` | `analysis/funds/` |
| 1 | Data Exploration | data | `/explore-data` | `01-data-exploration.md` | `analysis/funds/` |
| 2 | Data Validation | data | `/validate-data` | `02-data-validation.md` | `analysis/funds/` |
| 3 | Performance vs Benchmark/Category | finance | `/variance-analysis` | `03-performance-variance.md` | `analysis/funds/` |
| 4 | Category Research | big data | `/financial-research-analyst` | `04-category-research.md` | `analysis/funds/` |
| 5 | Fund Research | LSEG | `/equity-research` | `05-fund-research.md` | `analysis/funds/` |
| 6 | Intelligence Scraper | Bright Data | `/scraper-builder` | `06-scraper-build.md` | `analysis/funds/` |
| 7 | Final Verdict | — | (synthesis) | `07-final-recommendation.md` | `output/funds/` |
| 8 | Plain-English Summary | — | (summarization) | `08-summary.md` | `output/funds/` |

Stage 0 fetches NAV history from **[mfapi.in](https://www.mfapi.in)** (free, no key, backed by
AMFI's daily NAV data) and computes trailing CAGR (1y/3y/5y/10y/since inception), 1-year
volatility, and max drawdown directly from the NAV series. It has **no expense ratio, AUM,
holdings, exit load, or benchmark return** — Stages 4–6 source those from Value Research,
moneycontrol, Morningstar India, Tickertape, and AMC factsheets, and flag clearly when a
figure is unavailable.

---

## Setup

Both pipelines fetch live data over HTTP via the `requests` library (bundled with
`yfinance`). Install once:

```
python3 -m pip install -r requirements.txt
```

- **Stocks (`/analyze-stock`)** use [`yfinance`](https://pypi.org/project/yfinance/), which
  covers **Indian stocks** through Yahoo Finance via the NSE suffix `.NS` (`RELIANCE.NS`) or
  BSE suffix `.BO` (`RELIANCE.BO`); prices come back in ₹ INR. US tickers are passed bare
  (`NVDA`).
- **Funds (`/analyze-fund`)** use [mfapi.in](https://www.mfapi.in) directly via `requests` —
  no extra dependency beyond what's already in `requirements.txt`.

Both commands run their fetch automatically (Stage 0) and will offer to install the
dependency if it's missing.

## Plugins

The stages 1–6 of both pipelines call external plugin commands (`data`, `finance`,
`big data`, `LSEG`, `Bright Data`). If a plugin is not installed, that stage runs in
**fallback mode** — Claude performs the analysis itself, marks the file, and continues. Every
fallback is recorded in the final report. Confirm installed plugins by typing `/` in Claude
Code.

## Layout

```
.
├── .claude/commands/
│   ├── analyze-stock.md        # /analyze-stock orchestrator
│   └── analyze-fund.md         # /analyze-fund orchestrator
├── scripts/
│   ├── fetch_data.py           # Stage 0 for stocks: yfinance + screener.in
│   └── fetch_fund_data.py      # Stage 0 for funds: mfapi.in (AMFI NAV)
├── requirements.txt            # yfinance, requests, beautifulsoup4
├── analysis/
│   ├── stocks/<TICKER>/        # Stage 0 data + six stage files per stock (git-ignored)
│   │   └── README.md
│   └── funds/<FUND_NAME>/      # Stage 0 data + six stage files per fund (git-ignored)
│       └── README.md
├── output/
│   ├── stocks/<TICKER>/        # final report + summary per stock
│   │   └── README.md
│   └── funds/<FUND_NAME>/      # final report + summary per fund
│       └── README.md
├── .gitignore
├── LICENSE
└── README.md
```

## Disclaimer

Output is automated analysis, not personal financial advice. Confirm the underlying numbers
before acting.

---

Full design spec: `stock-analyzer-spec.md` (kept in Downloads).
