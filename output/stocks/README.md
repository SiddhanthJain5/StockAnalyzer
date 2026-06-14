# `output/stocks/` — final report for stocks

Each stock gets **one folder here, keyed by name only** — `<TICKER>/` — holding the single
**final recommendation**. Re-running the same stock updates it in place:

| File | Stage | Reads |
|------|-------|-------|
| `07-final-recommendation.md` | Final Verdict | `01`–`06` from `analysis/stocks/<TICKER>/` |
| `08-summary.md` | Plain-English TL;DR | `01`–`06` + `07-final-recommendation.md` |

Mutual funds use the parallel `/analyze-fund` pipeline → `output/funds/` (see
`../funds/README.md`).

**Open `08-summary.md` first** — it's a short, jargon-free, one-line-per-point summary of the
verdict meant for a non-technical reader. `07` is the full detailed report behind it.

This is the decision document — it synthesizes the six analysis files into a
**BUY / HOLD / SELL** verdict with conviction, entry guidance, the case in three cited
bullets, key risks, and what to watch next. The verdict, conviction, and both folder paths
are also printed to the terminal at the end of the run.

Run folders are git-ignored by default (see `../.gitignore`). Commit one explicitly to keep it.
