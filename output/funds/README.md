# `output/funds/` — final report for mutual funds

Each fund gets **one folder here, keyed by name only** — `<FUND_NAME>/` — holding the single
**final recommendation**. Re-running the same fund updates it in place:

| File | Stage | Reads |
|------|-------|-------|
| `07-final-recommendation.md` | Final Verdict | `01`–`06` from `analysis/funds/<FUND_NAME>/` |
| `08-summary.md` | Plain-English TL;DR | `07-final-recommendation.md` |

Stocks use the parallel `/analyze-stock` pipeline → `output/stocks/` (see
`../stocks/README.md`).

**Open `08-summary.md` first** — it's a short, jargon-free, one-line-per-point summary of the
verdict meant for a non-technical reader. `07` is the full detailed report behind it.

This is the decision document — it synthesizes the six analysis files into one of
**Continue/Start SIP · Hold — No Fresh Investment · Switch to Alternative · Exit/Redeem**
with conviction, SIP-vs-lumpsum investment guidance, the case in three cited bullets, key
risks, and what to watch next. The verdict, conviction, and both folder paths are also
printed to the terminal at the end of the run.

Run folders are git-ignored by default (see `../.gitignore`). Commit one explicitly to keep it.
