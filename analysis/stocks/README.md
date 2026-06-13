# `analysis/stocks/` — stage outputs for stocks

Each stock gets **one folder here, keyed by name only** — `<TICKER>/` — holding the **six
analysis stage files**. Re-running `/analyze-stock` for the same stock **updates these files
in place** with current data (each carries a `Last updated:` line) rather than creating a new
folder. The final verdict is written separately to `output/stocks/` (see
`../../output/stocks/README.md`).

Mutual funds use the parallel `/analyze-fund` pipeline under `analysis/funds/` and
`output/funds/` — see `../funds/README.md`.

| File | Stage | Reads |
|------|-------|-------|
| `00-market-data.md` / `.json` | Live Data Fetch (yfinance) | — |
| `01-data-exploration.md`  | Explore Data       | `00` |
| `02-data-validation.md`   | Validate Data      | `01` |
| `03-variance-analysis.md` | Variance Analysis  | `01`, `02` |
| `04-sector-research.md`   | Sector Research    | — |
| `05-equity-research.md`   | Equity Research    | `04` |
| `06-scraper-build.md`     | Scraper Builder    | — |

Handoff between stages is through the filesystem, so a run is auditable and re-runnable.
Stage 7 reads all six of these and writes the final report into `output/stocks/<TICKER>/`.

Run folders are git-ignored by default (see `../.gitignore`). Commit one explicitly to keep it.
