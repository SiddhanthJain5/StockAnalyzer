#!/usr/bin/env python3
"""Live mutual-fund data fetch for the /analyze-fund pipeline (Stage 0).

India-only. Uses mfapi.in (free, no key) for NAV history, fund metadata, and
scheme search. From the NAV series this computes CAGR over standard windows,
volatility, and max drawdown — the core numbers a fund verdict needs.

Usage:
    python3 scripts/fetch_fund_data.py "parag parikh flexi cap" --outdir analysis/funds/PARAG_PARIKH_FLEXI_CAP
    python3 scripts/fetch_fund_data.py 122639 --outdir analysis/funds/PARAG_PARIKH_FLEXI_CAP --scheme-code

If a name is given and matches multiple schemes, all candidates are written to
candidates.json under --outdir and the script exits non-zero so the caller can
ask the user to disambiguate (e.g. Direct vs Regular, Growth vs IDCW).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

API = "https://api.mfapi.in/mf"


def log(msg: str) -> None:
    print(f"[fetch_fund_data] {msg}", file=sys.stderr)


def search_schemes(query: str, session) -> list[dict]:
    r = session.get(f"{API}/search", params={"q": query}, timeout=20)
    r.raise_for_status()
    return r.json()


def get_scheme(code: int | str, session) -> dict:
    r = session.get(f"{API}/{code}", timeout=20)
    r.raise_for_status()
    return r.json()


def parse_nav_series(data: list[dict]) -> list[tuple[datetime, float]]:
    """mfapi returns newest-first as DD-MM-YYYY strings; return oldest-first."""
    series = []
    for row in data:
        try:
            d = datetime.strptime(row["date"], "%d-%m-%Y")
            nav = float(row["nav"])
        except (ValueError, KeyError):
            continue
        series.append((d, nav))
    series.reverse()
    return series


def nav_on_or_before(series: list[tuple[datetime, float]], target: datetime) -> float | None:
    """Latest NAV at or before `target`; falls back to the earliest point if target predates history."""
    candidate = None
    for d, nav in series:
        if d <= target:
            candidate = nav
        else:
            break
    return candidate if candidate is not None else (series[0][1] if series else None)


def cagr(start: float, end: float, years: float) -> float | None:
    if not start or start <= 0 or years <= 0:
        return None
    return round(((end / start) ** (1 / years) - 1) * 100, 2)


def compute_returns(series: list[tuple[datetime, float]]) -> dict:
    if len(series) < 2:
        return {}
    latest_date, latest_nav = series[-1]
    out: dict = {"as_of": latest_date.strftime("%Y-%m-%d"), "latest_nav": latest_nav}

    windows = {"1y": 1, "3y": 3, "5y": 5, "10y": 10}
    for label, yrs in windows.items():
        target = latest_date - timedelta(days=int(365.25 * yrs))
        start_nav = nav_on_or_before(series, target)
        if start_nav and target >= series[0][0]:
            out[f"cagr_{label}"] = cagr(start_nav, latest_nav, yrs)
        else:
            out[f"cagr_{label}"] = None  # not enough history

    first_date, first_nav = series[0]
    total_years = (latest_date - first_date).days / 365.25
    out["cagr_since_inception"] = cagr(first_nav, latest_nav, total_years)
    out["inception_date"] = first_date.strftime("%Y-%m-%d")
    out["years_of_history"] = round(total_years, 1)

    # 1y daily volatility (annualized) + max drawdown over full history.
    one_year_ago = latest_date - timedelta(days=365)
    recent = [(d, n) for d, n in series if d >= one_year_ago]
    if len(recent) > 5:
        daily_returns = [
            (recent[i][1] / recent[i - 1][1]) - 1
            for i in range(1, len(recent))
            if recent[i - 1][1] > 0
        ]
        if daily_returns:
            mean = sum(daily_returns) / len(daily_returns)
            variance = sum((x - mean) ** 2 for x in daily_returns) / len(daily_returns)
            out["volatility_1y_annualized_pct"] = round((variance ** 0.5) * (252 ** 0.5) * 100, 2)

    peak = series[0][1]
    max_dd = 0.0
    for _, nav in series:
        peak = max(peak, nav)
        dd = (nav / peak) - 1
        max_dd = min(max_dd, dd)
    out["max_drawdown_pct"] = round(max_dd * 100, 2)

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch live Indian mutual-fund data via mfapi.in.")
    ap.add_argument("query", help="Fund name to search, or a scheme code with --scheme-code")
    ap.add_argument("--outdir", required=True, help="Folder to write data files into")
    ap.add_argument("--scheme-code", action="store_true",
                    help="Treat `query` as an exact mfapi.in scheme code")
    args = ap.parse_args()

    try:
        import requests
    except ImportError:
        log("requests not installed. Run: pip install -r requirements.txt")
        return 2

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    if args.scheme_code:
        scheme_code = args.query
    else:
        log(f"searching schemes for '{args.query}' …")
        try:
            candidates = search_schemes(args.query, session)
        except Exception as e:  # noqa: BLE001
            log(f"ERROR: scheme search failed ({e})")
            return 3
        if not candidates:
            log(f"ERROR: no schemes found for '{args.query}'. "
                "Try a more specific name (fund house + category).")
            return 3
        if len(candidates) > 1:
            (outdir / "candidates.json").write_text(
                json.dumps(candidates, indent=2), encoding="utf-8"
            )
            log(f"{len(candidates)} schemes matched '{args.query}' — "
                f"wrote candidates.json. Re-run with --scheme-code <schemeCode>, "
                f"picking the right plan (Direct/Regular) and option (Growth/IDCW).")
            for c in candidates[:15]:
                log(f"  {c['schemeCode']}: {c['schemeName']}")
            return 4
        scheme_code = candidates[0]["schemeCode"]

    log(f"fetching scheme {scheme_code} …")
    try:
        scheme = get_scheme(scheme_code, session)
    except Exception as e:  # noqa: BLE001
        log(f"ERROR: failed to fetch scheme {scheme_code} ({e})")
        return 3

    meta = scheme.get("meta", {})
    series = parse_nav_series(scheme.get("data", []))
    if not series:
        log(f"ERROR: scheme {scheme_code} returned no NAV history")
        return 3

    returns = compute_returns(series)

    data = {
        "scheme_code": meta.get("scheme_code", scheme_code),
        "scheme_name": meta.get("scheme_name"),
        "fund_house": meta.get("fund_house"),
        "scheme_category": meta.get("scheme_category"),
        "scheme_type": meta.get("scheme_type"),
        "isin_growth": meta.get("isin_growth"),
        "currency": "INR",
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": "mfapi.in (AMFI NAV data)",
        "returns": returns,
        "nav_points": len(series),
    }
    data["_history"] = [
        {"date": d.strftime("%Y-%m-%d"), "nav": n} for d, n in series
    ]

    (outdir / "00-fund-data.json").write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )
    write_markdown(data, outdir / "00-fund-data.md")
    log(f"wrote {outdir/'00-fund-data.md'} and 00-fund-data.json "
        f"({data['nav_points']} NAV points, since {returns.get('inception_date')})")
    return 0


def fmt_pct(v) -> str:
    return "—" if v is None else f"{v:+.2f}%"


def write_markdown(data: dict, path: Path) -> None:
    r = data["returns"]
    lines = [
        f"# 00 — Live Fund Data · {data['scheme_name']} ({data['scheme_code']})",
        "",
        f"> Source: {data['source']} · Fetched: {data['fetched_at']}",
        f"> Fund house: {data['fund_house']} · Category: {data['scheme_category']}",
        f"> ISIN (Growth): {data.get('isin_growth') or '—'} · Currency: INR",
        "",
        "This file is the **live data layer**. Stages 1–6 must use these figures as the "
        "ground truth instead of model memory, and flag anything that looks stale or off.",
        "",
        "## NAV",
        f"- Latest NAV: **₹{r.get('latest_nav')}** as of {r.get('as_of')}",
        f"- History: {data['nav_points']} daily points since {r.get('inception_date')} "
        f"(~{r.get('years_of_history')} years)",
        "",
        "## Trailing Returns (CAGR)",
        f"- 1Y: {fmt_pct(r.get('cagr_1y'))} · 3Y: {fmt_pct(r.get('cagr_3y'))} · "
        f"5Y: {fmt_pct(r.get('cagr_5y'))} · 10Y: {fmt_pct(r.get('cagr_10y'))}",
        f"- Since inception: {fmt_pct(r.get('cagr_since_inception'))}",
        "",
        "## Risk",
        f"- 1Y annualized volatility: "
        f"{r.get('volatility_1y_annualized_pct', '—')}%",
        f"- Max drawdown (full history): {r.get('max_drawdown_pct', '—')}%",
        "",
        "_Note: this file has NO expense ratio, exit load, AUM, portfolio holdings, or "
        "benchmark/category-average return — mfapi.in does not provide these. Stage 6 "
        "(scraper design) should target Value Research / moneycontrol / AMC factsheet for "
        "that data; Stage 4 should source category-average returns for comparison._",
        "",
        f"_Raw JSON (with full NAV history): `00-fund-data.json`._",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
