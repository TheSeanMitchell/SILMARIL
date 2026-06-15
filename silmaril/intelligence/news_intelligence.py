"""
SILMARIL — News & Event Intelligence (Phase 1, deterministic / no LLM)
=====================================================================

Thesis (operator): *the written word is predictive; the numbers are reactive.*
News and dated events set up the thesis and the watchlist — numbers trigger the
entry/exit. This module reads the data SILMARIL already produces each cycle and
turns it into three forward-looking, fully explainable views:

  1. EVENT CALENDAR  — every dated catalyst the feed already ingests (~1 month
     out) PLUS a curated, extensible registry of major scheduled/anticipated
     events much further ahead (FOMC, jobs, quad-witching, anticipated IPOs).
  2. ETF REGIME BASKETS — sector groupings (Technology→XLK, Energy→XLE, …) with
     each basket's aggregate signal, conviction, headline volume and news state.
  3. NEWS MOMENTUM — the names the news is loudest about right now, with the
     direction of that coverage. (Cross-day repetition accrues once we persist a
     rolling store — see ROLLING note below; this is today's snapshot.)

Everything is compartmentalized into STOCKS (the focus) vs OTHER valuables
(crypto / tokens), because the operator wants them shown side-by-side but apart.

Inputs (read-only, already on disk):
  docs/data/signals.json    — debates[]: ticker, price, consensus, verdicts,
                              asset_class, sector, recent_headlines[], tags{news_state,…}
  docs/data/catalysts.json  — daily[]/weekly[]: date,time,ticker,type,note,magnitude,links

Output:
  docs/data/news_intelligence.json

Nothing here touches trade execution. Wiring these signals INTO trade decisions
(news notes inside each trade deal, regime nowcast with teeth) is Phase 2.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

VERSION = "intel-1.0"

# ───────────────────────────────────────────────────────────────────────────
# Sector → representative ETF basket. Equity/ETF sectors are "stocks"; Crypto
# and Token are "other valuables". Extend freely — unknown sectors fall into
# an "Other" basket rather than being dropped.
# ───────────────────────────────────────────────────────────────────────────
STOCK_BASKETS: Dict[str, Dict[str, str]] = {
    "Technology":     {"etf": "XLK", "label": "Technology"},
    "Software":       {"etf": "IGV", "label": "Software"},
    "Semiconductors": {"etf": "SMH", "label": "Semiconductors"},
    "Communication":  {"etf": "XLC", "label": "Communication Services"},
    "Discretionary":  {"etf": "XLY", "label": "Consumer Discretionary"},
    "Staples":        {"etf": "XLP", "label": "Consumer Staples"},
    "Energy":         {"etf": "XLE", "label": "Energy"},
    "Financials":     {"etf": "XLF", "label": "Financials"},
    "Healthcare":     {"etf": "XLV", "label": "Health Care"},
    "Industrials":    {"etf": "XLI", "label": "Industrials"},
    "Materials":      {"etf": "XLB", "label": "Materials"},
    "Real Estate":    {"etf": "XLRE", "label": "Real Estate"},
    "Utilities":      {"etf": "XLU", "label": "Utilities"},
    "Commodities":    {"etf": "DBC", "label": "Commodities (broad)"},
}
OTHER_BASKETS: Dict[str, Dict[str, str]] = {
    "Crypto": {"etf": "—", "label": "Crypto (majors)"},
    "Token":  {"etf": "—", "label": "Tokens / alt-coins"},
}

# ───────────────────────────────────────────────────────────────────────────
# CURATED FORWARD EVENT REGISTRY — the "way ahead" layer the feed lacks.
# Dated entries are real, verified anchors (2026 FOMC decision days, first-Friday
# jobs reports, quad-witching). Undated entries are *anticipated* — we DELIBERATELY
# do not invent dates; they ride a watchlist until a date is confirmed. Edit this
# list to track anything you expect to spark an investment moment.
# ───────────────────────────────────────────────────────────────────────────
CURATED_DATED_EVENTS: List[Dict[str, Any]] = [
    # ── SpaceX (SPCX) IPO — VERIFIED (S-1 public 2026-05-20; Reuters/CNBC/WSJ).
    # Largest IPO in history: ~556M shares @ $135, ~$75B raise, ~$1.75-2T valuation,
    # Nasdaq ticker SPCX (now contains xAI/Starlink/Grok post Feb-2026 merger).
    # Underwriters: Goldman (lead), Morgan Stanley, BofA, Citi, JPMorgan.
    {"date": "2026-06-11", "type": "ipo_pricing", "magnitude": "very_high", "ticker": "SPCX", "note": "SpaceX (SPCX) IPO pricing after close — $135 indicated, ~$75B raise (largest ever)"},
    {"date": "2026-06-12", "type": "ipo_debut", "magnitude": "very_high", "ticker": "SPCX", "note": "SpaceX (SPCX) first day of trading on Nasdaq — the largest IPO in market history"},
    # 2026 FOMC rate-decision days (verified vs federalreserve.gov)
    {"date": "2026-07-29", "type": "fomc", "magnitude": "very_high", "ticker": "SPY", "note": "FOMC rate decision + statement + presser"},
    {"date": "2026-09-16", "type": "fomc", "magnitude": "very_high", "ticker": "SPY", "note": "FOMC rate decision (+ economic projections / dot plot)"},
    {"date": "2026-10-28", "type": "fomc", "magnitude": "very_high", "ticker": "SPY", "note": "FOMC rate decision + statement + presser"},
    {"date": "2026-12-09", "type": "fomc", "magnitude": "very_high", "ticker": "SPY", "note": "FOMC rate decision (+ economic projections / dot plot)"},
    {"date": "2027-01-28", "type": "fomc", "magnitude": "very_high", "ticker": "SPY", "note": "FOMC rate decision + statement + presser"},
    # BLS Employment Situation — first Friday of each month (verified calendar)
    {"date": "2026-07-03", "type": "bls_empl", "magnitude": "very_high", "ticker": "", "note": "Jobs report (BLS Employment Situation, Jun)"},
    {"date": "2026-08-07", "type": "bls_empl", "magnitude": "very_high", "ticker": "", "note": "Jobs report (BLS Employment Situation, Jul)"},
    {"date": "2026-09-04", "type": "bls_empl", "magnitude": "very_high", "ticker": "", "note": "Jobs report (BLS Employment Situation, Aug)"},
    {"date": "2026-10-02", "type": "bls_empl", "magnitude": "very_high", "ticker": "", "note": "Jobs report (BLS Employment Situation, Sep)"},
    {"date": "2026-11-06", "type": "bls_empl", "magnitude": "very_high", "ticker": "", "note": "Jobs report (BLS Employment Situation, Oct)"},
    {"date": "2026-12-04", "type": "bls_empl", "magnitude": "very_high", "ticker": "", "note": "Jobs report (BLS Employment Situation, Nov)"},
    # Quarterly quad-witching OPEX (3rd Friday of Mar/Jun/Sep/Dec)
    {"date": "2026-09-18", "type": "opex_quarterly", "magnitude": "high", "ticker": "", "note": "Quarterly OPEX (triple/quad witching)"},
    {"date": "2026-12-18", "type": "opex_quarterly", "magnitude": "high", "ticker": "", "note": "Quarterly OPEX (triple/quad witching)"},
]
CURATED_WATCHLIST: List[Dict[str, Any]] = [
    # Anticipated catalysts with no confirmed date — tracked, not fabricated.
    # (SpaceX/SPCX has moved to the DATED list above — its IPO is now confirmed.)
    {"label": "Stripe IPO", "status": "anticipated", "tickers": [], "note": "Largest private fintech; long-anticipated. Date TBD."},
    {"label": "Databricks IPO", "status": "anticipated", "tickers": [], "note": "AI/data-platform listing widely expected. Date TBD."},
    {"label": "OpenAI restructuring / listing", "status": "anticipated", "tickers": ["MSFT"], "note": "Any liquidity event would ripple through AI names. Date TBD."},
    {"label": "Anthropic financing milestones", "status": "anticipated", "tickers": [], "note": "Frontier-AI capital events move sentiment across the AI complex. Date TBD."},
]

# Signal → numeric direction, for momentum scoring.
_SIGNAL_DIR = {
    "STRONG_BUY": 1.0, "BUY": 0.6, "HOLD": 0.0, "ABSTAIN": 0.0,
    "SELL": -0.6, "STRONG_SELL": -1.0,
}
_NEWS_DIR = {"POSITIVE_NEWS": 1.0, "NEGATIVE_NEWS": -1.0, "NORMAL": 0.0}


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception as e:  # noqa: BLE001
        log.warning("news_intelligence: could not read %s — %s", path, e)
        return None


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _days_until(date_str: str, today: date) -> Optional[int]:
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        return (d - today).days
    except Exception:  # noqa: BLE001
        return None


def _is_stock(asset_class: str, sector: str) -> bool:
    """Stocks = equity/ETF and not a crypto/token sector."""
    if sector in ("Crypto", "Token"):
        return False
    return asset_class in ("equity", "etf", "")


# ───────────────────────────────────────────────────────────────────────────
# Builders
# ───────────────────────────────────────────────────────────────────────────
def _build_calendar(catalysts: Any, sector_by_ticker: Dict[str, str], today: date) -> Dict[str, Any]:
    feed: List[Dict[str, Any]] = []
    if isinstance(catalysts, dict):
        for bucket in ("daily", "weekly"):
            for e in (catalysts.get(bucket) or []):
                if not isinstance(e, dict):
                    continue
                feed.append(e)

    def _row(e: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
        d = e.get("date")
        if not d:
            return None
        du = _days_until(d, today)
        if du is None or du < 0:  # past events drop off
            return None
        tkr = (e.get("ticker") or "").upper()
        return {
            "date": d[:10],
            "days_until": du,
            "type": e.get("type", "event"),
            "magnitude": e.get("magnitude", "high"),
            "ticker": tkr,
            "sector": sector_by_ticker.get(tkr, ""),
            "note": e.get("note", ""),
            "source": source,
        }

    dated: List[Dict[str, Any]] = []
    seen = set()
    for e in feed:
        r = _row(e, "feed")
        if r:
            key = (r["date"], r["type"], r["ticker"], r["note"][:20])
            if key not in seen:
                seen.add(key)
                dated.append(r)
    for e in CURATED_DATED_EVENTS:
        r = _row(e, "curated")
        if r:
            key = (r["date"], r["type"], r["ticker"], r["note"][:20])
            if key not in seen:
                seen.add(key)
                dated.append(r)

    dated.sort(key=lambda r: (r["date"], r["ticker"]))

    high_impact = [r for r in dated if r["magnitude"] == "very_high"]
    return {
        "dated": dated,
        "watchlist": list(CURATED_WATCHLIST),
        "next_high_impact": high_impact[0] if high_impact else None,
        "counts": {
            "total_dated": len(dated),
            "from_feed": sum(1 for r in dated if r["source"] == "feed"),
            "curated_ahead": sum(1 for r in dated if r["source"] == "curated"),
            "very_high": len(high_impact),
            "watchlist": len(CURATED_WATCHLIST),
            "furthest_days": dated[-1]["days_until"] if dated else 0,
        },
    }


def _build_baskets(debates: List[Dict[str, Any]], basket_map: Dict[str, Dict[str, str]],
                   stock_side: bool) -> List[Dict[str, Any]]:
    by_sector: Dict[str, List[Dict[str, Any]]] = {}
    for d in debates:
        sector = d.get("sector", "") or "Other"
        if _is_stock(d.get("asset_class", ""), sector) != stock_side:
            continue
        by_sector.setdefault(sector, []).append(d)

    out: List[Dict[str, Any]] = []
    for sector, members in by_sector.items():
        spec = basket_map.get(sector, {"etf": "—", "label": sector})
        sig_mix: Dict[str, int] = {}
        news_mix: Dict[str, int] = {}
        score_sum = 0.0
        headline_count = 0
        ranked: List[Dict[str, Any]] = []
        for m in members:
            cons = m.get("consensus") or {}
            sig = (cons.get("signal") or "HOLD").upper()
            sig_mix[sig] = sig_mix.get(sig, 0) + 1
            score_sum += float(cons.get("score") or 0.0)
            ns = ((m.get("tags") or {}).get("news_state") or "NORMAL")
            news_mix[ns] = news_mix.get(ns, 0) + 1
            nh = len(m.get("recent_headlines") or [])
            headline_count += nh
            ranked.append({
                "ticker": m.get("ticker", ""),
                "signal": sig,
                "score": round(float(cons.get("score") or 0.0), 3),
                "headlines": nh,
                "news_state": ns,
            })
        n = len(members)
        ranked.sort(key=lambda r: (-abs(r["score"]), -r["headlines"]))
        net = score_sum / n if n else 0.0
        bull = sig_mix.get("BUY", 0) + sig_mix.get("STRONG_BUY", 0)
        bear = sig_mix.get("SELL", 0) + sig_mix.get("STRONG_SELL", 0)
        stance = "bullish" if net > 0.15 and bull >= bear else (
                 "bearish" if net < -0.15 and bear > bull else "mixed")
        out.append({
            "basket": spec["label"],
            "sector": sector,
            "etf": spec["etf"],
            "members": n,
            "net_score": round(net, 3),
            "stance": stance,
            "signal_mix": sig_mix,
            "news_states": news_mix,
            "headline_count": headline_count,
            "active_news": sum(1 for v in news_mix if v != "NORMAL") if isinstance(news_mix, dict) else 0,
            "top_members": ranked[:6],
        })
    # busiest / strongest baskets first
    out.sort(key=lambda b: (-b["headline_count"], -abs(b["net_score"])))
    return out


def _build_momentum(debates: List[Dict[str, Any]], stock_side: bool, limit: int = 15) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for d in debates:
        sector = d.get("sector", "") or "Other"
        if _is_stock(d.get("asset_class", ""), sector) != stock_side:
            continue
        headlines = d.get("recent_headlines") or []
        if not headlines:
            continue
        cons = d.get("consensus") or {}
        sig = (cons.get("signal") or "HOLD").upper()
        ns = ((d.get("tags") or {}).get("news_state") or "NORMAL")
        direction = _SIGNAL_DIR.get(sig, 0.0)
        news_bias = _NEWS_DIR.get(ns, 0.0)
        # Deterministic loudness×direction score: volume of coverage, signed by
        # the consensus direction and nudged by the classified news state.
        score = len(headlines) * (direction + 0.5 * news_bias)
        rows.append({
            "ticker": d.get("ticker", ""),
            "sector": sector,
            "headlines": len(headlines),
            "signal": sig,
            "score": round(cons.get("score", 0.0), 3) if cons else 0.0,
            "news_state": ns,
            "momentum": round(score, 2),
            "top_headline": (headlines[0] or {}).get("title", "")[:140] if isinstance(headlines[0], dict) else "",
        })
    # loudest first, then strongest signed momentum
    rows.sort(key=lambda r: (-r["headlines"], -abs(r["momentum"])))
    return rows[:limit]


def build_news_intelligence(data_dir: Path) -> Dict[str, Any]:
    """Read signals.json + catalysts.json, write docs/data/news_intelligence.json."""
    data_dir = Path(data_dir)
    signals = _load(data_dir / "signals.json") or {}
    catalysts = _load(data_dir / "catalysts.json")
    debates: List[Dict[str, Any]] = signals.get("debates", []) if isinstance(signals, dict) else []
    today = _today()

    sector_by_ticker = {
        (d.get("ticker") or "").upper(): (d.get("sector") or "")
        for d in debates if d.get("ticker")
    }

    stock_debates = [d for d in debates if _is_stock(d.get("asset_class", ""), d.get("sector", ""))]
    other_debates = [d for d in debates if not _is_stock(d.get("asset_class", ""), d.get("sector", ""))]

    payload = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "thesis": "Words are predictive; numbers are reactive. Events and news set up the thesis; price triggers the entry/exit.",
        "summary": {
            "stocks_tracked": len(stock_debates),
            "other_tracked": len(other_debates),
            "names_in_news": sum(1 for d in debates if d.get("recent_headlines")),
        },
        "event_calendar": _build_calendar(catalysts, sector_by_ticker, today),
        "stocks": {
            "universe_count": len(stock_debates),
            "baskets": _build_baskets(stock_debates, STOCK_BASKETS, stock_side=True),
            "momentum": _build_momentum(stock_debates, stock_side=True),
        },
        "other": {
            "universe_count": len(other_debates),
            "baskets": _build_baskets(other_debates, OTHER_BASKETS, stock_side=False),
            "momentum": _build_momentum(other_debates, stock_side=False),
        },
        "notes": [
            "Stocks are the focus; 'other valuables' (crypto/tokens) are tracked side-by-side but separately.",
            "Calendar = real ingested catalysts (~1mo out) + a curated, extensible forward registry (FOMC/jobs/OPEX verified; IPOs anticipated, dates TBD).",
            "Momentum is today's snapshot (loudness x direction). Cross-day headline repetition accrues once a rolling store is persisted (Phase 1.5).",
            "Deterministic and explainable — no LLM, no tokens, no external calls. Display-only in Phase 1; not yet wired into trade execution.",
        ],
    }

    out_path = data_dir / "news_intelligence.json"
    try:
        out_path.write_text(json.dumps(payload, indent=2))
        log.info("news_intelligence: wrote %s (%d dated events, %d stock baskets)",
                 out_path, payload["event_calendar"]["counts"]["total_dated"],
                 len(payload["stocks"]["baskets"]))
    except Exception as e:  # noqa: BLE001
        log.warning("news_intelligence: could not write %s — %s", out_path, e)

    return payload


if __name__ == "__main__":  # manual run: python -m silmaril.intelligence.news_intelligence
    import sys
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")
    p = build_news_intelligence(d)
    print(json.dumps(p["summary"], indent=2))
    print("calendar counts:", json.dumps(p["event_calendar"]["counts"]))
