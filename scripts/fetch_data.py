#!/usr/bin/env python3
"""Live market-data fetch for the /analyze-stock pipeline (Stage 0).

Pulls quote, valuation, fundamentals and price history from Yahoo Finance via
yfinance, then writes both machine-readable JSON and a human-readable markdown
summary into the stock's analysis folder. The six analysis stages read these
files instead of relying on the model's memory.

yfinance covers Indian stocks: use the NSE suffix `.NS` (e.g. RELIANCE.NS) or the
BSE suffix `.BO` (e.g. RELIANCE.BO). US tickers are passed bare (e.g. NVDA).

Usage:
    python3 scripts/fetch_data.py RELIANCE.NS --outdir analysis/RELIANCE
    python3 scripts/fetch_data.py NVDA --outdir analysis/NVDA
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def log(msg: str) -> None:
    print(f"[fetch_data] {msg}", file=sys.stderr)


def safe(d: dict, *keys):
    """Return the first present, non-None key from a dict."""
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def is_indian(symbol: str) -> bool:
    s = symbol.upper()
    return s.endswith(".NS") or s.endswith(".BO")


def base_symbol(symbol: str) -> str:
    """Strip an exchange suffix to the bare ticker (RELIANCE.NS -> RELIANCE)."""
    return symbol.upper().split(".")[0]


def fetch_screener(symbol: str) -> dict:
    """Scrape India-fundamentals from screener.in.

    Screener is India-only and adds what Yahoo lacks for Indian names: a quarterly
    OPM/EPS trend, ROCE, compounded growth, and a Pros/Cons read. It does NOT expose a
    business-segment (e.g. Jio/Retail/O2C) table — those live in annual-report notes — so
    this fills the *fundamentals* gap, not a literal segment split.

    Returns a dict; on any failure returns {"error": ...} so the run never breaks.
    """
    if not is_indian(symbol):
        return {"skipped": "screener.in is India-only; symbol is not .NS/.BO"}

    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as e:  # bundled with yfinance, but be safe
        return {"error": f"missing dependency for screener scrape: {e}"}

    base = base_symbol(symbol)
    headers = {"User-Agent": "Mozilla/5.0 (analyze-stock pipeline; +screener fetch)"}
    html = None
    used_url = None
    # Prefer consolidated (group-level) figures; fall back to standalone.
    for url in (
        f"https://www.screener.in/company/{base}/consolidated/",
        f"https://www.screener.in/company/{base}/",
    ):
        try:
            r = requests.get(url, headers=headers, timeout=20)
        except Exception as e:  # noqa: BLE001
            log(f"warning: screener request failed for {url} ({e})")
            continue
        if r.status_code == 200 and "top-ratios" in r.text:
            html, used_url = r.text, url
            break
    if html is None:
        return {"error": f"screener.in returned no usable page for '{base}' "
                         "(check the screener symbol — it may differ from the NSE ticker)"}

    soup = BeautifulSoup(html, "html.parser")

    # --- Top key ratios ---
    key_ratios = {}
    for li in soup.select("#top-ratios li"):
        name_el = li.select_one(".name")
        val_el = li.select_one(".value") or li.select_one(".nowrap")
        if name_el and val_el:
            name = name_el.get_text(strip=True)
            val = " ".join(val_el.get_text(" ", strip=True).split())
            key_ratios[name] = val

    # --- Quarterly trend (keep the last 6 columns of the rows that matter) ---
    quarters = {}
    qsec = soup.select_one("#quarters table")
    if qsec:
        cols = [th.get_text(strip=True) for th in qsec.select("thead th")][1:]
        wanted_prefixes = ("Sales", "Operating Profit", "OPM", "Net Profit",
                           "EPS", "Financing Profit", "Revenue")
        rows = {}
        for tr in qsec.select("tbody tr"):
            cells = [td.get_text(strip=True) for td in tr.select("td")]
            if not cells:
                continue
            label = cells[0].replace("\xa0", " ").strip(" +")
            if label.startswith(wanted_prefixes):
                rows[label] = cells[1:]
        n = 6
        quarters = {
            "columns": cols[-n:],
            "rows": {k: v[-n:] for k, v in rows.items()},
        }

    # --- Compounded growth tables (Sales / Profit / Price CAGR / ROE) ---
    growth = {}
    for tbl in soup.select("#profit-loss table.ranges-table"):
        trs = tbl.select("tr")
        if not trs:
            continue
        title = trs[0].get_text(" ", strip=True)
        entries = {}
        for tr in trs[1:]:
            cells = [c.get_text(strip=True) for c in tr.select("td")]
            if len(cells) >= 2:
                entries[cells[0].rstrip(":")] = cells[1]
        if entries:
            growth[title] = entries

    # --- Pros / Cons ---
    def bullets(sel):
        box = soup.select_one(sel)
        return [li.get_text(strip=True) for li in box.select("li")] if box else []

    return {
        "url": used_url,
        "basis": "consolidated" if "consolidated" in (used_url or "") else "standalone",
        "key_ratios": key_ratios,
        "quarters": quarters,
        "growth": growth,
        "pros": bullets(".pros"),
        "cons": bullets(".cons"),
    }


def fetch(symbol: str) -> dict:
    import yfinance as yf  # imported here so --help works without the dep

    tk = yf.Ticker(symbol)

    # .info can be flaky; fall back to fast_info where possible.
    try:
        info = tk.info or {}
    except Exception as e:  # noqa: BLE001
        log(f"warning: .info failed ({e}); continuing with fast_info only")
        info = {}

    try:
        fast = dict(tk.fast_info)
    except Exception:  # noqa: BLE001
        fast = {}

    currency = safe(info, "currency") or fast.get("currency") or (
        "INR" if is_indian(symbol) else None
    )

    # Price history (1y daily) for technical context.
    history = []
    try:
        hist = tk.history(period="1y", interval="1d")
        if not hist.empty:
            closes = hist["Close"].dropna()
            history = [
                {"date": idx.strftime("%Y-%m-%d"), "close": round(float(v), 2)}
                for idx, v in closes.items()
            ]
    except Exception as e:  # noqa: BLE001
        log(f"warning: history fetch failed ({e})")

    last_price = (
        fast.get("last_price")
        or safe(info, "currentPrice", "regularMarketPrice", "previousClose")
        or (history[-1]["close"] if history else None)
    )

    # Simple derived technicals from history.
    technicals = {}
    if history:
        closes = [h["close"] for h in history]
        def sma(n):
            return round(sum(closes[-n:]) / n, 2) if len(closes) >= n else None
        technicals = {
            "52w_high": round(max(closes), 2),
            "52w_low": round(min(closes), 2),
            "sma_50": sma(50),
            "sma_200": sma(200),
            "pct_from_52w_high": (
                round((last_price / max(closes) - 1) * 100, 1)
                if last_price else None
            ),
        }

    data = {
        "symbol": symbol.upper(),
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "source": "Yahoo Finance via yfinance",
        "market": "India (NSE/BSE)" if is_indian(symbol) else "US/Other",
        "currency": currency,
        "name": safe(info, "longName", "shortName"),
        "exchange": safe(info, "exchange", "fullExchangeName") or fast.get("exchange"),
        "sector": safe(info, "sector"),
        "industry": safe(info, "industry"),
        "quote": {
            "last_price": last_price,
            "previous_close": safe(info, "previousClose"),
            "day_high": safe(info, "dayHigh") or fast.get("day_high"),
            "day_low": safe(info, "dayLow") or fast.get("day_low"),
            "market_cap": safe(info, "marketCap") or fast.get("market_cap"),
        },
        "valuation": {
            "trailing_pe": safe(info, "trailingPE"),
            "forward_pe": safe(info, "forwardPE"),
            "price_to_book": safe(info, "priceToBook"),
            "ev_to_ebitda": safe(info, "enterpriseToEbitda"),
            "dividend_yield": safe(info, "dividendYield"),
        },
        "fundamentals": {
            "revenue": safe(info, "totalRevenue"),
            "ebitda": safe(info, "ebitda"),
            "profit_margins": safe(info, "profitMargins"),
            "return_on_equity": safe(info, "returnOnEquity"),
            "total_debt": safe(info, "totalDebt"),
            "total_cash": safe(info, "totalCash"),
            "debt_to_equity": safe(info, "debtToEquity"),
            "revenue_growth": safe(info, "revenueGrowth"),
            "earnings_growth": safe(info, "earningsGrowth"),
        },
        "analyst": {
            "recommendation": safe(info, "recommendationKey"),
            "num_analyst_opinions": safe(info, "numberOfAnalystOpinions"),
            "target_mean": safe(info, "targetMeanPrice"),
            "target_high": safe(info, "targetHighPrice"),
            "target_low": safe(info, "targetLowPrice"),
        },
        "technicals": technicals,
        "history_points": len(history),
    }

    # India fundamentals from screener.in (fills Yahoo's gaps; never blocks the run).
    log("fetching screener.in fundamentals …")
    data["screener"] = fetch_screener(symbol)

    data["_history"] = history  # kept in JSON, omitted from markdown summary
    return data


def fmt(v, currency: str | None = None, pct: bool = False) -> str:
    if v is None:
        return "—"
    if pct:
        # yfinance gives some ratios as fractions (0.18) and some as already-%.
        return f"{v * 100:.1f}%" if abs(v) < 1 else f"{v:.1f}%"
    if isinstance(v, (int, float)):
        prefix = f"{currency} " if currency else ""
        if abs(v) >= 1e7:
            return f"{prefix}{v:,.0f}"
        return f"{prefix}{v:,.2f}"
    return str(v)


def write_markdown(data: dict, path: Path) -> None:
    c = data.get("currency")
    q, val, f, a, t = (
        data["quote"], data["valuation"], data["fundamentals"],
        data["analyst"], data["technicals"],
    )
    lines = [
        f"# 00 — Live Market Data · {data.get('name') or data['symbol']} ({data['symbol']})",
        "",
        f"> Source: {data['source']} · Fetched: {data['fetched_at']}",
        f"> Market: {data['market']} · Currency: {c or '—'} · "
        f"Exchange: {data.get('exchange') or '—'}",
        f"> Sector: {data.get('sector') or '—'} / {data.get('industry') or '—'}",
        "",
        "This file is the **live data layer**. Stages 1–6 must use these figures as the "
        "ground truth instead of model memory, and flag anything that looks stale or off.",
        "",
        "## Quote",
        f"- Last price: **{fmt(q['last_price'], c)}**",
        f"- Previous close: {fmt(q['previous_close'], c)}",
        f"- Day range: {fmt(q['day_low'], c)} – {fmt(q['day_high'], c)}",
        f"- Market cap: {fmt(q['market_cap'], c)}",
        "",
        "## Valuation",
        f"- Trailing P/E: {fmt(val['trailing_pe'])} · Forward P/E: {fmt(val['forward_pe'])}",
        f"- Price/Book: {fmt(val['price_to_book'])} · EV/EBITDA: {fmt(val['ev_to_ebitda'])}",
        # yfinance returns dividendYield already as a percent (e.g. 0.46 = 0.46%).
        f"- Dividend yield: "
        f"{fmt(val['dividend_yield']) + '%' if val['dividend_yield'] is not None else '—'}",
        "",
        "## Fundamentals",
        f"- Revenue: {fmt(f['revenue'], c)} · EBITDA: {fmt(f['ebitda'], c)}",
        f"- Profit margin: {fmt(f['profit_margins'], pct=True)} · "
        f"ROE: {fmt(f['return_on_equity'], pct=True)}",
        f"- Total debt: {fmt(f['total_debt'], c)} · Total cash: {fmt(f['total_cash'], c)}",
        f"- Debt/Equity: {fmt(f['debt_to_equity'])} · "
        f"Revenue growth: {fmt(f['revenue_growth'], pct=True)} · "
        f"Earnings growth: {fmt(f['earnings_growth'], pct=True)}",
        "",
        "## Analyst Consensus",
        f"- Recommendation: **{a['recommendation'] or '—'}** "
        f"({fmt(a['num_analyst_opinions'])} analysts)",
        f"- Target (low/mean/high): {fmt(a['target_low'], c)} / "
        f"**{fmt(a['target_mean'], c)}** / {fmt(a['target_high'], c)}",
        "",
        "## Technicals (1y daily)",
        f"- 52w range: {fmt(t.get('52w_low'), c)} – {fmt(t.get('52w_high'), c)}",
        f"- 50-day SMA: {fmt(t.get('sma_50'), c)} · 200-day SMA: {fmt(t.get('sma_200'), c)}",
        f"- From 52w high: {fmt(t.get('pct_from_52w_high'))}%"
        if t.get("pct_from_52w_high") is not None else "- From 52w high: —",
        "",
    ]

    lines += _screener_markdown(data.get("screener") or {})

    lines += [
        f"_Raw JSON (with full price history + screener data): `00-market-data.json`._",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _screener_markdown(sc: dict) -> list[str]:
    """Render the screener.in block, degrading gracefully if it's empty/errored."""
    out = ["## Screener.in — India fundamentals"]
    if not sc or sc.get("skipped"):
        out += [f"- _Skipped: {sc.get('skipped', 'no data')}._", ""]
        return out
    if sc.get("error"):
        out += [f"- _Unavailable: {sc['error']}._", ""]
        return out

    out.append(f"> Source: {sc['url']} ({sc['basis']}). No business-segment split here — "
               "screener exposes consolidated fundamentals, not Jio/Retail/O2C lines.")
    out.append("")

    kr = sc.get("key_ratios") or {}
    if kr:
        priority = ["Stock P/E", "ROCE", "ROE", "Book Value", "Dividend Yield",
                    "Market Cap", "High / Low", "Face Value"]
        ordered = [k for k in priority if k in kr] + [k for k in kr if k not in priority]
        out.append("**Key ratios:** " + " · ".join(f"{k} {kr[k]}" for k in ordered))
        out.append("")

    q = sc.get("quarters") or {}
    if q.get("columns") and q.get("rows"):
        cols = q["columns"]
        out.append("**Quarterly trend** (last %d quarters):" % len(cols))
        out.append("")
        out.append("| Metric | " + " | ".join(cols) + " |")
        out.append("|" + "---|" * (len(cols) + 1))
        for label in ("Sales", "Operating Profit", "OPM", "Net Profit", "EPS in Rs"):
            row = next((v for k, v in q["rows"].items() if k.startswith(label)), None)
            if row:
                name = next(k for k in q["rows"] if k.startswith(label))
                out.append(f"| {name} | " + " | ".join(row) + " |")
        out.append("")

    g = sc.get("growth") or {}
    if g:
        out.append("**Compounded growth / returns:**")
        for title, entries in g.items():
            out.append(f"- {title}: "
                       + " · ".join(f"{k} {v}" for k, v in entries.items()))
        out.append("")

    pros, cons = sc.get("pros") or [], sc.get("cons") or []
    if pros:
        out.append("**Pros (screener):**")
        out += [f"- {p}" for p in pros]
        out.append("")
    if cons:
        out.append("**Cons (screener):**")
        out += [f"- {c}" for c in cons]
        out.append("")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch live market data via yfinance.")
    ap.add_argument("symbol", help="Ticker. Indian: RELIANCE.NS / .BO. US: NVDA")
    ap.add_argument("--outdir", required=True, help="Folder to write data files into")
    args = ap.parse_args()

    try:
        import yfinance  # noqa: F401
    except ImportError:
        log("yfinance not installed. Run: pip install -r requirements.txt")
        return 2

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    log(f"fetching {args.symbol} …")
    data = fetch(args.symbol)

    if data["quote"]["last_price"] is None and not data["_history"]:
        log(f"ERROR: no data returned for '{args.symbol}'. "
            "Check the symbol (Indian tickers need a .NS or .BO suffix).")
        return 3

    (outdir / "00-market-data.json").write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )
    write_markdown(data, outdir / "00-market-data.md")
    log(f"wrote {outdir/'00-market-data.md'} and 00-market-data.json "
        f"({data['history_points']} price points)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
