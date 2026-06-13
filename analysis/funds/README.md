# `analysis/funds/` — stage outputs for mutual funds

Each fund gets **one folder here, keyed by name only** — `<FUND_NAME>/` — holding the **live
NAV data file (`00`) and six analysis stage files (`01`–`06`)**. Re-running `/analyze-fund`
for the same fund **updates these files in place** with current data (each carries a
`Last updated:` line) rather than creating a new folder. The final verdict is written
separately to `output/funds/` (see `../../output/funds/README.md`).

Stocks use the parallel `/analyze-stock` pipeline under `analysis/stocks/` and
`output/stocks/` — see `../stocks/README.md`.

| File | Stage | Reads |
|------|-------|-------|
| `00-fund-data.md` / `.json` | Live NAV Fetch (mfapi.in / AMFI) | — |
| `01-data-exploration.md`    | Explore Data                    | `00` |
| `02-data-validation.md`     | Validate Data                   | `01` |
| `03-performance-variance.md`| Performance vs Benchmark/Category | `01`, `02`, `00` |
| `04-category-research.md`   | Category Research               | — |
| `05-fund-research.md`       | Fund Research                   | `04`, `00` |
| `06-scraper-build.md`       | Scraper Builder                 | — |

Handoff between stages is through the filesystem, so a run is auditable and re-runnable.
Stage 7 reads all six of these and writes the final report into `output/funds/<FUND_NAME>/`.

This pipeline is **India-only**: `00-fund-data.md` comes from mfapi.in (AMFI daily NAV) and
covers NAV, trailing CAGR, volatility, and max drawdown — but not expense ratio, AUM,
holdings, exit load, or benchmark returns. Stages 4–6 source those from Value Research,
moneycontrol, Morningstar India, Tickertape, and AMC factsheets.

Run folders are git-ignored by default (see `../.gitignore`). Commit one explicitly to keep it.
