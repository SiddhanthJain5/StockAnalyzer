"""Core analysis pipeline for the web app.

The `/analyze-stock` and `/analyze-fund` slash commands run an 8-stage pipeline
inside Claude Code, where stages 1-6 call Claude Code plugins. A public website
can't invoke those plugins (and a paid LLM call per request doesn't scale for free
public traffic), so this module:

- reuses the Stage-0 live-data fetchers (scripts/fetch_data.py,
  scripts/fetch_fund_data.py) as the ground-truth data layer, and
- replaces stages 1-8 with `webapp.scoring`, a rules-based engine that scores a
  fixed set of heuristics from that data and produces a verdict, conviction,
  plain-English bullets, risks, and guidance - the same shape as the pipeline's
  final report + summary, at zero cost.

Results are cached on disk per ticker/scheme so repeat visits (and the rate limiter
in main.py) don't re-hit yfinance/screener.in/mfapi.in on every page load.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

from scripts.fetch_data import base_symbol, fetch as fetch_stock_data, is_indian  # noqa: E402
from scripts.fetch_fund_data import (  # noqa: E402
    compute_returns,
    get_scheme,
    parse_nav_series,
    search_schemes,
)
from webapp import scoring  # noqa: E402

CACHE_DIR = ROOT / "webapp" / "cache"
CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", str(3600)))


class PipelineError(Exception):
    """User-facing error (bad symbol, ambiguous fund, missing data, ...)."""


# ---------------------------------------------------------------------------
# Disk cache - one JSON file per ticker/scheme code.
# ---------------------------------------------------------------------------

def _cache_path(kind: str, key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in key.upper())
    d = CACHE_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.json"


def _cache_read(kind: str, key: str) -> dict | None:
    p = _cache_path(kind, key)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - payload.get("cached_at", 0) > CACHE_TTL_SECONDS:
        return None
    return payload.get("result")


def _cache_write(kind: str, key: str, result: dict) -> None:
    _cache_path(kind, key).write_text(
        json.dumps({"cached_at": time.time(), "result": result}, indent=2, default=str)
    )


# ---------------------------------------------------------------------------
# Stocks
# ---------------------------------------------------------------------------

def analyze_stock(query: str, market: str) -> dict:
    """market is 'india' or 'us' - only used when the query has no exchange suffix."""
    query = (query or "").strip()
    if not query:
        raise PipelineError("Please enter a ticker or company name.")

    if "." in query:
        symbol = query.upper()
    elif (market or "india").lower() == "us":
        symbol = query.upper()
    else:
        symbol = f"{query.upper()}.NS"

    cached = _cache_read("stocks", symbol)
    if cached is not None:
        return cached

    data = fetch_stock_data(symbol)
    if data["quote"]["last_price"] is None and not data.get("_history"):
        raise PipelineError(
            f"No data found for '{query}'. Indian tickers need a .NS or .BO suffix - "
            f"try the India market toggle, or double-check the symbol."
        )

    currency_code = data.get("currency") or ("INR" if is_indian(symbol) else "USD")
    currency_symbol = "₹" if currency_code == "INR" else ("$" if currency_code == "USD" else currency_code)

    analysis = scoring.score_stock(data)

    result = {
        "type": "stock",
        "subject_name": data.get("name") or base_symbol(symbol),
        "subject_code": base_symbol(symbol),
        "market": data.get("market"),
        "currency_symbol": currency_symbol,
        "price_label": "Price now",
        "price_value": data["quote"]["last_price"],
        "as_of": data.get("fetched_at"),
        **analysis,
    }
    _cache_write("stocks", symbol, result)
    return result


# ---------------------------------------------------------------------------
# Mutual funds (India only)
# ---------------------------------------------------------------------------

def analyze_fund(query: str, scheme_code: str | None = None) -> dict:
    query = (query or "").strip()
    if not query and not scheme_code:
        raise PipelineError("Please enter a fund name or AMFI scheme code.")

    session = requests.Session()

    if scheme_code:
        code = str(scheme_code)
    elif query.isdigit():
        code = query
    else:
        try:
            candidates = search_schemes(query, session)
        except Exception as e:  # noqa: BLE001
            raise PipelineError(f"Fund search failed: {e}") from e
        if not candidates:
            raise PipelineError(
                f"No funds found for '{query}'. Try a more specific name "
                f"(fund house + category), or the AMFI scheme code."
            )
        if len(candidates) > 1:
            return {"type": "fund_candidates", "candidates": candidates[:15]}
        code = str(candidates[0]["schemeCode"])

    cached = _cache_read("funds", code)
    if cached is not None:
        return cached

    try:
        scheme = get_scheme(code, session)
    except Exception as e:  # noqa: BLE001
        raise PipelineError(f"Failed to fetch scheme {code}: {e}") from e

    meta = scheme.get("meta", {})
    series = parse_nav_series(scheme.get("data", []))
    if not series:
        raise PipelineError(f"Scheme {code} returned no NAV history.")

    returns = compute_returns(series)
    data = {
        "scheme_code": meta.get("scheme_code", code),
        "scheme_name": meta.get("scheme_name"),
        "fund_house": meta.get("fund_house"),
        "scheme_category": meta.get("scheme_category"),
        "scheme_type": meta.get("scheme_type"),
        "isin_growth": meta.get("isin_growth"),
        "currency": "INR",
        "returns": returns,
        "nav_points": len(series),
    }

    analysis = scoring.score_fund(data)

    result = {
        "type": "fund",
        "subject_name": data["scheme_name"],
        "subject_code": str(data["scheme_code"]),
        "market": "India",
        "currency_symbol": "₹",
        "price_label": "NAV now",
        "price_value": returns.get("latest_nav"),
        "as_of": returns.get("as_of"),
        **analysis,
    }
    _cache_write("funds", code, result)
    return result
