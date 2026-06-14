"""Rules-based analysis engine - no LLM, no paid API.

Turns the live data already fetched in Stage 0 (yfinance + screener.in for stocks,
mfapi.in/AMFI for funds) into a verdict, conviction, and plain-English write-up using
a small set of weighted heuristic "signals". Each signal contributes -2..+2 to a
total score; the score (relative to how many signals had data) decides the verdict,
and the signal texts are reused directly as the plain-English bullets.

This is intentionally simple and transparent - it's meant to give a useful first
read from the numbers, not to replace research.
"""
from __future__ import annotations

GENERIC_PLAIN_FILLER = [
    "Some of the usual checks had no data available for this one - treat this as a "
    "starting point, not the full picture.",
]

GENERIC_RISK_FILLERS = [
    "Broader market or macro moves (interest rates, global sentiment) can move this "
    "regardless of the specific checks above.",
    "This read is based only on the numbers above - news, management changes, or "
    "regulatory action aren't captured here.",
    "Past performance and current ratios don't guarantee what happens next.",
]

GENERIC_CASE_FILLERS = [
    "Nothing in the data above raises a major red flag beyond what's already listed.",
]


def _signal(contribution: float, text: str) -> dict:
    return {"contribution": contribution, "text": text}


def _top(signals: list[dict], sign: int, n: int) -> list[str]:
    """Top `n` signal texts. sign>0 -> positive contributions only, sign<0 -> negative
    only, sign==0 -> any, ranked by |contribution|."""
    if sign > 0:
        pool = [s for s in signals if s["contribution"] > 0]
    elif sign < 0:
        pool = [s for s in signals if s["contribution"] < 0]
    else:
        pool = signals
    pool = sorted(pool, key=lambda s: abs(s["contribution"]), reverse=True)
    return [s["text"] for s in pool[:n]]


def _verdict_buckets(signals: list[dict], verdict: str, bearish_verdicts: set):
    """Pick case_bullets (the strongest points in favor) and key_risks (against).

    For a bearish verdict, "the case" is the bear case, so the negative signals
    support it and the positive signals become the risks to that thesis - and
    vice versa otherwise. Either way the two lists draw from disjoint signs, so
    they never overlap.
    """
    if verdict in bearish_verdicts:
        case = _top(signals, -1, 3)
        risks = _top(signals, +1, 3)
    else:
        case = _top(signals, +1, 3)
        risks = _top(signals, -1, 3)

    case = (case + GENERIC_CASE_FILLERS)[:3]
    risks = (risks + GENERIC_RISK_FILLERS)[:3]
    return case, risks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_pct(v) -> float | None:
    """yfinance reports revenue/earnings growth and ROE as fractions (e.g. 1.4 = 140%),
    even above 1.0 for high-growth/high-ROE names - so always convert to a percent."""
    if v is None:
        return None
    return v * 100


def _parse_pct_str(s) -> float | None:
    """Parse screener.in style percentage strings, e.g. '10.3 %' or '18%' or '-9%'."""
    if s is None:
        return None
    try:
        return float(str(s).replace("%", "").replace(",", "").strip())
    except ValueError:
        return None


def _fmt_inr(value: float) -> str:
    if value >= 1e7:
        return f"₹{value / 1e7:.1f} crore"
    if value >= 1e5:
        return f"₹{value / 1e5:.1f} lakh"
    return f"₹{value:,.0f}"


# ---------------------------------------------------------------------------
# Stocks
# ---------------------------------------------------------------------------

_REC_MAP = {
    "strong_buy": (1, "Wall Street analysts rate this a 'Strong Buy' on average"),
    "buy": (0.5, "Wall Street analysts rate this a 'Buy' on average"),
    "hold": (0, "Wall Street analysts rate this a 'Hold' on average"),
    "sell": (-0.5, "Wall Street analysts rate this a 'Sell' on average"),
    "strong_sell": (-1, "Wall Street analysts rate this a 'Strong Sell' on average"),
}


def score_stock(data: dict) -> dict:
    q, val, fund, analyst, tech = (
        data["quote"], data["valuation"], data["fundamentals"],
        data["analyst"], data["technicals"],
    )
    screener = data.get("screener") or {}
    price = q.get("last_price")
    signals: list[dict] = []

    # 1. Analyst recommendation
    rec = (analyst.get("recommendation") or "").lower()
    if rec in _REC_MAP:
        weight, phrase = _REC_MAP[rec]
        n = analyst.get("num_analyst_opinions")
        suffix = f" ({n} analysts)." if n else "."
        signals.append(_signal(weight, phrase + suffix))

    # 2. Analyst target upside/downside
    target = analyst.get("target_mean")
    if price and target:
        upside = (target / price - 1) * 100
        if upside > 15:
            signals.append(_signal(2, f"Analysts' average target implies about {upside:.0f}% upside from here."))
        elif upside > 5:
            signals.append(_signal(1, f"Analysts' average target is modestly above the current price (about {upside:.0f}% upside)."))
        elif upside < -15:
            signals.append(_signal(-2, f"Analysts' average target is about {abs(upside):.0f}% below the current price."))
        elif upside < -5:
            signals.append(_signal(-1, f"Analysts' average target is slightly below the current price (about {abs(upside):.0f}% downside)."))
        else:
            signals.append(_signal(0, "Trading close to analysts' average price target - not much upside or downside priced in by analysts."))

    # 3. 52-week momentum
    pct_high = tech.get("pct_from_52w_high")
    if pct_high is not None:
        if pct_high >= -5:
            signals.append(_signal(1, "Trading near its 52-week high - strong recent momentum."))
        elif pct_high <= -30:
            signals.append(_signal(-1, f"Down about {abs(pct_high):.0f}% from its 52-week high - well off its recent peak."))
        else:
            signals.append(_signal(0, f"Trading about {abs(pct_high):.0f}% below its 52-week high - neither at a high nor deeply discounted."))

    # 4. Moving-average trend
    sma50, sma200 = tech.get("sma_50"), tech.get("sma_200")
    if price and sma50 and sma200:
        if price > sma50 > sma200:
            signals.append(_signal(1, "Price is above both its 50-day and 200-day averages - an uptrend."))
        elif price < sma50 < sma200:
            signals.append(_signal(-1, "Price is below both its 50-day and 200-day averages - a downtrend."))
        else:
            signals.append(_signal(0, "Price is mixed relative to its short- and long-term averages - no clear trend."))

    # 5. Valuation - trailing P/E
    pe = val.get("trailing_pe")
    if pe and pe > 0:
        if pe < 15:
            signals.append(_signal(1, f"P/E (price vs earnings) of {pe:.1f} is on the cheaper side."))
        elif pe > 40:
            signals.append(_signal(-1, f"P/E (price vs earnings) of {pe:.1f} is high - priced for a lot of future growth."))
        else:
            signals.append(_signal(0, f"P/E (price vs earnings) of {pe:.1f} is in a fairly typical range."))

    # 6. Revenue growth
    rev_g = _norm_pct(fund.get("revenue_growth"))
    if rev_g is not None:
        if rev_g > 10:
            signals.append(_signal(1, f"Revenue grew about {rev_g:.0f}% year-over-year - the business is growing."))
        elif rev_g < 0:
            signals.append(_signal(-1, f"Revenue shrank about {abs(rev_g):.0f}% year-over-year."))
        else:
            signals.append(_signal(0, f"Revenue growth of about {rev_g:.0f}% year-over-year is modest."))

    # 7. Earnings growth
    earn_g = _norm_pct(fund.get("earnings_growth"))
    if earn_g is not None:
        if earn_g > 10:
            signals.append(_signal(1, f"Earnings grew about {earn_g:.0f}% year-over-year."))
        elif earn_g < 0:
            signals.append(_signal(-1, f"Earnings fell about {abs(earn_g):.0f}% year-over-year."))
        else:
            signals.append(_signal(0, f"Earnings growth of about {earn_g:.0f}% year-over-year is modest."))

    # 8. Profitability - ROE
    roe = _norm_pct(fund.get("return_on_equity"))
    if roe is not None:
        if roe > 15:
            signals.append(_signal(1, f"Return on equity (profit vs shareholder money) of about {roe:.0f}% is strong."))
        elif roe < 5:
            signals.append(_signal(-1, f"Return on equity (profit vs shareholder money) of about {roe:.0f}% is on the low side."))
        else:
            signals.append(_signal(0, f"Return on equity (profit vs shareholder money) of about {roe:.0f}% is moderate."))

    # 9. Leverage - Debt/Equity
    de = fund.get("debt_to_equity")
    if de is not None:
        if de < 50:
            signals.append(_signal(1, f"Debt/Equity of about {de:.0f}% is conservative - low reliance on borrowed money."))
        elif de > 150:
            signals.append(_signal(-1, f"Debt/Equity of about {de:.0f}% is high - meaningful borrowed money on the books."))
        else:
            signals.append(_signal(0, f"Debt/Equity of about {de:.0f}% is moderate."))

    # --- India-only signals from screener.in ---
    key_ratios = screener.get("key_ratios") or {}
    growth = screener.get("growth") or {}

    # 10. ROCE
    roce = _parse_pct_str(key_ratios.get("ROCE"))
    if roce is not None:
        if roce > 15:
            signals.append(_signal(1, f"ROCE (return on capital employed) of about {roce:.1f}% shows efficient use of capital."))
        elif roce < 8:
            signals.append(_signal(-1, f"ROCE (return on capital employed) of about {roce:.1f}% is on the lower side."))
        else:
            signals.append(_signal(0, f"ROCE (return on capital employed) of about {roce:.1f}% is moderate."))

    # 11/12. 5-year compounded sales/profit growth
    for label, key in (("sales", "Compounded Sales Growth"), ("profit", "Compounded Profit Growth")):
        g = _parse_pct_str((growth.get(key) or {}).get("5 Years"))
        if g is not None:
            if g > 12:
                signals.append(_signal(1, f"{label.capitalize()} has compounded at about {g:.0f}%/year over the last 5 years."))
            elif g < 0:
                signals.append(_signal(-1, f"{label.capitalize()} has shrunk by about {abs(g):.0f}%/year on average over the last 5 years."))
            else:
                signals.append(_signal(0, f"{label.capitalize()} has compounded at about {g:.0f}%/year over the last 5 years - moderate."))

    # 13. screener.in pros/cons net sentiment
    pros, cons = screener.get("pros") or [], screener.get("cons") or []
    if pros or cons:
        diff = len(pros) - len(cons)
        weight = max(-2, min(2, diff))
        for p in pros[:2]:
            signals.append(_signal(1, p))
        for c in cons[:2]:
            signals.append(_signal(-1, c))
        if not pros and not cons:
            signals.append(_signal(0, "No notable pros or cons flagged by screener.in."))
        # `weight` already reflected via the individual pros/cons signals above.
        del weight

    # --- Shareholding-pattern signals from screener.in (India) ---
    shp_rows = (screener.get("shareholding") or {}).get("rows") or {}

    def _shp_series(prefix: str) -> list[float]:
        """Latest-last list of parsed % for the first row whose label matches `prefix`."""
        for label, vals in shp_rows.items():
            if label.lower().startswith(prefix):
                return [p for p in (_parse_pct_str(v) for v in vals) if p is not None]
        return []

    promoter = _shp_series("promoter")
    dii = _shp_series("dii")

    # 14. Promoter/government stake level & minimum-public-shareholding (MPS) overhang.
    # Listed companies must keep >=25% public float (promoter <=75%); a stake above that
    # means more shares must eventually be sold to the public - a supply overhang.
    if promoter:
        latest = promoter[-1]
        trend = (promoter[-1] - promoter[0]) if len(promoter) >= 2 else 0.0
        if latest > 75:
            gap = latest - 75
            selling = " and have been actively selling down" if trend <= -2 else ""
            signals.append(_signal(-1,
                f"Promoters/government hold about {latest:.0f}%{selling} - above the 75% ceiling "
                f"listed companies must meet, so roughly {gap:.0f}% more of the stock has to be "
                f"sold to the public over time, a supply overhang that can weigh on the price "
                f"until it's done."))
        elif latest >= 50:
            signals.append(_signal(1,
                f"Promoters hold a controlling stake of about {latest:.0f}% - meaningful skin in "
                f"the game."))

    # 15. Domestic-institutional (DII) ownership trend - rising DII often absorbs promoter
    # selling and signals institutional conviction.
    if len(dii) >= 2:
        dchange = dii[-1] - dii[0]
        if dchange >= 2:
            signals.append(_signal(1,
                f"Domestic institutions have been increasing their holding (to about "
                f"{dii[-1]:.0f}%) - buying interest that helps absorb shares being sold."))
        elif dchange <= -2:
            signals.append(_signal(-1,
                f"Domestic institutions have been trimming their holding (to about "
                f"{dii[-1]:.0f}%) - reduced institutional support."))

    # --- Tally ---
    total = sum(s["contribution"] for s in signals)
    n = len(signals)
    ratio = total / n if n else 0.0

    if ratio >= 0.3:
        verdict = "BUY"
    elif ratio <= -0.3:
        verdict = "SELL"
    else:
        verdict = "HOLD"

    if n >= 4 and abs(ratio) >= 0.5:
        conviction = "High"
    elif n >= 2 and abs(ratio) >= 0.25:
        conviction = "Medium"
    else:
        conviction = "Low"

    n_pos = sum(1 for s in signals if s["contribution"] > 0)
    n_neg = sum(1 for s in signals if s["contribution"] < 0)
    if n == 0:
        conviction_reason = "Not enough data was available to form a confident view."
    elif n_pos == n_neg:
        conviction_reason = f"{n_pos} of {n} checks lean positive and {n_neg} lean negative - a mixed picture without a clear majority."
    else:
        leader = "positive" if n_pos > n_neg else "negative"
        conviction_reason = f"{max(n_pos, n_neg)} of {n} checks lean {leader} (vs {min(n_pos, n_neg)} the other way)."

    # Price context
    if pct_high is not None:
        if pct_high >= -3:
            price_context = "near its 52-week high"
        elif pct_high <= -25:
            price_context = f"down about {abs(pct_high):.0f}% from its 52-week high"
        else:
            price_context = f"about {abs(pct_high):.0f}% below its 52-week high"
    else:
        price_context = ""

    plain_bullets = _top(signals, 0, 6)
    if len(plain_bullets) < 4:
        plain_bullets = plain_bullets + GENERIC_PLAIN_FILLER
    case_bullets, key_risks = _verdict_buckets(signals, verdict, {"SELL"})

    currency_symbol = "₹" if data.get("currency") == "INR" else ("$" if data.get("currency") == "USD" else (data.get("currency") or ""))

    if verdict == "BUY":
        action_value = (
            f"Current levels (around {currency_symbol}{price:,.2f}) look reasonable given the checks "
            f"above - consider buying in tranches rather than all at once."
            if price else "Current levels look reasonable based on the checks above; consider buying in tranches."
        )
        walk_away_if = "If the negative checks above worsen further (e.g. earnings declines continue or it breaks below its 200-day average), the case weakens."
    elif verdict == "SELL":
        action_value = "Not an attractive entry at current levels based on these checks; if you already hold it, consider trimming on strength."
        walk_away_if = "If the positive checks above strengthen (e.g. earnings growth turns positive and it reclaims its averages), revisit the thesis."
    else:
        if sma200:
            action_value = (
                f"Consider waiting for either a pullback toward its 200-day average "
                f"(around {currency_symbol}{sma200:,.2f}) or clearer improvement in the checks above before adding."
            )
        else:
            action_value = "Consider waiting for clearer improvement in the checks above before adding."
        walk_away_if = "If the negative checks above get worse over the next couple of quarters, lean toward selling; if the positive checks strengthen, lean toward buying."

    return {
        "verdict": verdict,
        "conviction": conviction,
        "conviction_reason": conviction_reason,
        "price_context": price_context,
        "plain_bullets": plain_bullets,
        "case_bullets": case_bullets,
        "key_risks": key_risks,
        "action_value": action_value,
        "walk_away_if": walk_away_if,
        "watch_for": "The next quarterly results and any change in analyst price targets.",
    }


# ---------------------------------------------------------------------------
# Mutual funds (India only)
# ---------------------------------------------------------------------------

_EQUITY_HINTS = ("equity", "elss", "flexi", "multi cap", "large cap", "mid cap",
                 "small cap", "focused", "value", "contra", "dividend yield",
                 "sectoral", "thematic", "index")
_DEBT_HINTS = ("debt", "gilt", "liquid", "bond", "money market", "overnight",
               "income", "credit risk", "banking and psu", "corporate bond",
               "dynamic bond")
_HYBRID_HINTS = ("hybrid", "balanced", "arbitrage")


def _category_thresholds(category: str) -> tuple[float, float, str]:
    cat = (category or "").lower()
    if any(h in cat for h in _DEBT_HINTS):
        return 8.0, 6.0, category.lower() if category else "debt fund"
    if any(h in cat for h in _HYBRID_HINTS):
        return 10.0, 7.0, category.lower() if category else "hybrid fund"
    if any(h in cat for h in _EQUITY_HINTS):
        return 12.0, 8.0, category.lower() if category else "equity fund"
    return 10.0, 7.0, category.lower() if category else "fund of this type"


def score_fund(data: dict) -> dict:
    r = data["returns"]
    category = data.get("scheme_category") or ""
    good, ok, label = _category_thresholds(category)
    article = "an" if label[:1].lower() in "aeiou" else "a"

    cagr_1y, cagr_3y = r.get("cagr_1y"), r.get("cagr_3y")
    cagr_5y, cagr_10y = r.get("cagr_5y"), r.get("cagr_10y")
    cagr_since = r.get("cagr_since_inception")
    vol = r.get("volatility_1y_annualized_pct")
    dd = r.get("max_drawdown_pct")
    years = r.get("years_of_history") or 0

    long_term = next((v for v in (cagr_5y, cagr_10y, cagr_since, cagr_3y, cagr_1y) if v is not None), None)

    signals: list[dict] = []

    # 1. Long-term CAGR vs category-style threshold
    if long_term is not None:
        if long_term >= good:
            signals.append(_signal(2, f"Long-term return of about {long_term:.1f}%/year is strong for {article} {label}."))
        elif long_term >= ok:
            signals.append(_signal(1, f"Long-term return of about {long_term:.1f}%/year is reasonable for {article} {label}."))
        elif long_term >= 0:
            signals.append(_signal(-1, f"Long-term return of about {long_term:.1f}%/year is below typical expectations for {article} {label}."))
        else:
            signals.append(_signal(-2, f"This fund has lost money over the long term (about {long_term:.1f}%/year) - a significant red flag."))

    # 2. Recent (1y) vs long-term trend
    if cagr_1y is not None and long_term is not None:
        gap = cagr_1y - long_term
        if gap >= 5:
            signals.append(_signal(1, f"Recent 1-year return ({cagr_1y:+.1f}%) is running ahead of its longer-term average ({long_term:.1f}%)."))
        elif gap <= -10:
            signals.append(_signal(-1, f"Recent 1-year return ({cagr_1y:+.1f}%) has cooled off well below its longer-term average ({long_term:.1f}%) - a rough patch lately."))
        else:
            signals.append(_signal(0, f"Recent 1-year return ({cagr_1y:+.1f}%) is broadly in line with its longer-term average ({long_term:.1f}%)."))

    # 3. Risk-adjusted return (CAGR vs volatility)
    if long_term is not None and vol and vol > 0:
        rv = long_term / vol
        if rv >= 1.2:
            signals.append(_signal(1, f"It has earned about {long_term:.1f}%/year against {vol:.1f}% volatility - decent reward for the risk taken."))
        elif rv <= 0.5:
            signals.append(_signal(-1, f"It has earned about {long_term:.1f}%/year against {vol:.1f}% volatility - not much reward for the risk."))
        else:
            signals.append(_signal(0, f"Its return-to-volatility balance ({long_term:.1f}%/year vs {vol:.1f}% volatility) is about average."))

    # 4. Max drawdown severity
    if dd is not None:
        if dd <= -50:
            signals.append(_signal(-1, f"Its biggest historical drop was about {abs(dd):.0f}% - quite severe; this can happen again."))
        elif dd >= -20:
            signals.append(_signal(1, f"Its biggest historical drop was a relatively contained {abs(dd):.0f}% - lower volatility than many peers."))
        else:
            signals.append(_signal(0, f"Its biggest historical drop was about {abs(dd):.0f}% - typical for an equity-oriented fund; expect swings."))

    # 5. Consistency - 3y vs longer-term track record
    ref = next((v for v in (cagr_10y, cagr_since) if v is not None), None)
    if cagr_3y is not None and ref is not None:
        gap = cagr_3y - ref
        if gap >= 5:
            signals.append(_signal(1, f"3-year returns ({cagr_3y:.1f}%) are running ahead of its longer-term track record ({ref:.1f}%)."))
        elif gap <= -5:
            signals.append(_signal(-1, f"3-year returns ({cagr_3y:.1f}%) are below its longer-term track record ({ref:.1f}%) - recent years have been weaker."))
        else:
            signals.append(_signal(0, f"3-year returns ({cagr_3y:.1f}%) are broadly consistent with its longer-term track record ({ref:.1f}%)."))

    if not signals:
        signals.append(_signal(0, "Too little NAV history was available to compute meaningful return/risk metrics."))

    total = sum(s["contribution"] for s in signals)
    n = len(signals)
    ratio = total / n if n else 0.0

    if long_term is not None and long_term < 0:
        verdict = "Exit/Redeem"
    elif ratio <= -0.6:
        verdict = "Exit/Redeem"
    elif ratio >= 0.3:
        verdict = "Continue/Start SIP"
    else:
        verdict = "Hold - No Fresh Investment"

    if years >= 5 and n >= 3 and abs(ratio) >= 0.5:
        conviction = "High"
    elif n >= 2 and abs(ratio) >= 0.25:
        conviction = "Medium"
    else:
        conviction = "Low"

    n_pos = sum(1 for s in signals if s["contribution"] > 0)
    n_neg = sum(1 for s in signals if s["contribution"] < 0)
    if n_pos == n_neg:
        conviction_reason = f"{n_pos} of {n} checks lean positive and {n_neg} lean negative - a mixed picture without a clear majority."
    else:
        leader = "positive" if n_pos > n_neg else "negative"
        conviction_reason = f"{max(n_pos, n_neg)} of {n} checks lean {leader} (vs {min(n_pos, n_neg)} the other way)."
    if years < 3:
        conviction = "Low"
        conviction_reason += f" Also, only {years:.1f} years of history is available, so take this with a grain of salt."

    # Price context: long-run growth framed as a lump-sum multiple
    if cagr_since is not None and years > 0:
        multiple_value = 100_000 * (1 + cagr_since / 100) ** years
        price_context = (
            f"up about {cagr_since:.1f}%/year on average since inception - "
            f"₹1 lakh invested then would be worth roughly {_fmt_inr(multiple_value)} now"
        )
    elif long_term is not None:
        price_context = f"averaging about {long_term:+.1f}%/year over the longest period available"
    else:
        price_context = ""

    plain_bullets = _top(signals, 0, 6)
    if len(plain_bullets) < 4:
        plain_bullets = plain_bullets + GENERIC_PLAIN_FILLER
    case_bullets, key_risks = _verdict_buckets(signals, verdict, {"Exit/Redeem"})

    if verdict == "Continue/Start SIP":
        action_value = "A regular SIP fits well here - the numbers above support staying invested. Lumpsum is fine too if you have a long (5y+) horizon and can stomach the swings noted below."
        walk_away_if = "If returns over the next few years fall meaningfully below the long-term average shown above for an extended period, revisit."
    elif verdict == "Exit/Redeem":
        action_value = "Consider redeeming and reallocating to a fund with a stronger long-term track record in this category."
        walk_away_if = "This guidance already points to exiting - revisit only if performance recovers sharply and sustainably."
    else:
        action_value = "Keep any existing SIP running, but a fresh lumpsum isn't strongly supported by the numbers above right now."
        walk_away_if = "If the recent underperformance noted above continues for several more quarters without recovery, consider switching to an alternative."

    return {
        "verdict": verdict,
        "conviction": conviction,
        "conviction_reason": conviction_reason,
        "price_context": price_context,
        "plain_bullets": plain_bullets,
        "case_bullets": case_bullets,
        "key_risks": key_risks,
        "action_value": action_value,
        "walk_away_if": walk_away_if,
        "watch_for": "How the next NAV update compares to its longer-term average return shown above.",
    }
