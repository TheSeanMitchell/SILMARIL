"""
silmaril.ingestion.market_leaders — What's actually moving today.

A daily snapshot of market leaders so the agents have an external, ground-truth
read on "what's in the green" — top gainers, losers, most-active, and the megacap
leaders by market cap. This is the "note what's doing well, for learning" feed.

SOURCE STRATEGY (robust, key-first):
    Lead with the JSON APIs SILMARIL already has keys for, because scraping HTML
    breaks the moment a site changes markup:
      1. Financial Modeling Prep  (FMP_API_KEY)      gainers/losers/actives + screener
      2. Alpha Vantage            (ALPHA_VANTAGE...)  TOP_GAINERS_LOSERS
      3. Polygon                  (POLYGON_API_KEY)   snapshot gainers/losers
      4. stockanalysis.com pages  (no key)            best-effort HTML fallback
    The first source that returns data for a category wins; the rest are skipped.

It writes docs/data/market_leaders.json with normalized gainers/losers/actives,
the megacap leaders, a de-duped "leaders_watchlist", and a cross-reference flag
for each name: is it already in the system's universe / a current debate / held?
That cross-reference is what makes it actionable — it shows which real movers the
system is and is NOT paying attention to.

Read-only ingestion. Writes one file, touches nothing else. Rate-friendly: one
request per source per category, intended for ~once/day (off-hours) cadence.
Network failures degrade gracefully to an empty-but-valid file with a note.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "market-leaders-1.0"
HTTP_TIMEOUT = 12
TOP_N = 25            # per category
MEGACAP_N = 60        # biggest companies to keep
_USER_AGENT = "SILMARIL/educational-research (paper-trading; contact via repo)"


# ── io ──────────────────────────────────────────────────────────────
def _sanitize(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def _dump(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(_sanitize(obj), f, indent=2, default=str, allow_nan=False)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _get_json(url: str) -> Optional[Any]:
    try:
        import requests
        r = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": _USER_AGENT})
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _get_text(url: str) -> Optional[str]:
    try:
        import requests
        r = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": _USER_AGENT})
        if r.status_code != 200:
            return None
        return r.text
    except Exception:
        return None


def _f(x) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(str(x).replace("%", "").replace(",", "").replace("$", "").strip())
    except Exception:
        return None


def _mktcap_to_float(s: str) -> Optional[float]:
    """'5.20T' / '930.22B' / '566.48M' -> float dollars."""
    if not s:
        return None
    m = re.match(r"\s*([\d,.]+)\s*([TBMK]?)\s*$", str(s), re.I)
    if not m:
        return _f(s)
    val = _f(m.group(1))
    if val is None:
        return None
    mult = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3, "": 1.0}.get(m.group(2).upper(), 1.0)
    return val * mult


def _row(ticker, name=None, price=None, change_pct=None, market_cap=None,
         volume=None, source=None) -> Optional[Dict[str, Any]]:
    t = str(ticker or "").upper().strip()
    if not t or not re.match(r"^[A-Z][A-Z.\-]{0,6}$", t):
        return None
    return {
        "ticker": t,
        "name": (str(name).strip() if name else None),
        "price": _f(price),
        "change_pct": _f(change_pct),
        "market_cap": (market_cap if isinstance(market_cap, (int, float)) else _mktcap_to_float(market_cap)),
        "volume": _f(volume),
        "source": source,
    }


def _dedupe(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for r in rows:
        if not r:
            continue
        if r["ticker"] in seen:
            continue
        seen.add(r["ticker"])
        out.append(r)
    return out


# ── source normalizers (pure — unit-testable) ──────────────────────
def norm_fmp_movers(data: Any, source: str) -> List[Dict[str, Any]]:
    rows = []
    for d in (data or []):
        if not isinstance(d, dict):
            continue
        rows.append(_row(d.get("symbol"), d.get("name"), d.get("price"),
                         d.get("changesPercentage"), None, None, source))
    return _dedupe(rows)


def norm_fmp_screener(data: Any) -> List[Dict[str, Any]]:
    rows = []
    for d in (data or []):
        if not isinstance(d, dict):
            continue
        rows.append(_row(d.get("symbol"), d.get("companyName") or d.get("name"),
                         d.get("price"), None, d.get("marketCap"),
                         d.get("volume"), "fmp_screener"))
    rows = [r for r in _dedupe(rows) if r and r.get("market_cap")]
    rows.sort(key=lambda r: r["market_cap"] or 0, reverse=True)
    return rows[:MEGACAP_N]


def norm_alpha_vantage(data: Any) -> Dict[str, List[Dict[str, Any]]]:
    out = {"gainers": [], "losers": [], "most_active": []}
    if not isinstance(data, dict):
        return out
    keymap = [("top_gainers", "gainers"), ("top_losers", "losers"),
              ("most_actively_traded", "most_active")]
    for src_key, dst in keymap:
        for d in (data.get(src_key) or []):
            if not isinstance(d, dict):
                continue
            out[dst].append(_row(d.get("ticker"), None, d.get("price"),
                                 d.get("change_percentage"), None,
                                 d.get("volume"), "alpha_vantage"))
        out[dst] = _dedupe(out[dst])
    return out


def norm_polygon(data: Any, source: str) -> List[Dict[str, Any]]:
    rows = []
    for d in ((data or {}).get("tickers") or []):
        if not isinstance(d, dict):
            continue
        day = d.get("day") or {}
        rows.append(_row(d.get("ticker"), None, day.get("c"),
                         d.get("todaysChangePerc"), None, day.get("v"), source))
    return _dedupe(rows)


def parse_stockanalysis_table(html: str, source: str) -> List[Dict[str, Any]]:
    """Best-effort parse of a stockanalysis.com server-rendered table.
    Captures ticker via /stocks/<t>/ links and the numeric cells that follow.
    Returns [] (never raises) if the markup doesn't match — it's a fallback."""
    if not html:
        return []
    rows: List[Dict[str, Any]] = []
    # Each row links the ticker, then has cells for name / mktcap / price / %chg.
    row_re = re.compile(
        r'/stocks/([a-zA-Z.\-]{1,7})/?"[^>]*>([^<]*)</a>.*?'
        r'(?:<td[^>]*>([^<]*)</td>\s*){0,5}', re.I | re.S)
    # Simpler robust approach: split on row anchors, pull numbers per chunk.
    chunks = re.split(r'/stocks/', html)
    for ch in chunks[1:]:
        mt = re.match(r'([a-zA-Z.\-]{1,7})', ch)
        if not mt:
            continue
        tkr = mt.group(1)
        # numbers in this chunk up to the next row
        seg = ch[:600]
        # percentage like -3.62% or 4.24%
        pcts = re.findall(r'(-?\d+\.\d+)%', seg)
        # market cap like 5.20T / 930.22B
        caps = re.findall(r'\b(\d+(?:\.\d+)?[TBM])\b', seg)
        # bare price like 214.75 / 1,079.57
        prices = re.findall(r'>\s*([\d,]+\.\d{2})\s*<', seg)
        r = _row(tkr, None,
                 prices[0] if prices else None,
                 pcts[0] if pcts else None,
                 caps[0] if caps else None,
                 None, source)
        if r:
            rows.append(r)
    return _dedupe(rows)[:TOP_N]


# ── source fetchers (key-first, graceful) ──────────────────────────
def fetch_movers() -> Dict[str, Any]:
    """Return {gainers, losers, most_active, sources_used:[...]}. First source
    that yields rows for a category wins."""
    fmp = os.environ.get("FMP_API_KEY")
    av = os.environ.get("ALPHA_VANTAGE_API_KEY")
    poly = os.environ.get("POLYGON_API_KEY")
    out = {"gainers": [], "losers": [], "most_active": [], "sources_used": []}

    if fmp:
        g = norm_fmp_movers(_get_json(f"https://financialmodelingprep.com/api/v3/stock_market/gainers?apikey={fmp}"), "fmp")
        l = norm_fmp_movers(_get_json(f"https://financialmodelingprep.com/api/v3/stock_market/losers?apikey={fmp}"), "fmp")
        a = norm_fmp_movers(_get_json(f"https://financialmodelingprep.com/api/v3/stock_market/actives?apikey={fmp}"), "fmp")
        if g or l or a:
            out["gainers"], out["losers"], out["most_active"] = g[:TOP_N], l[:TOP_N], a[:TOP_N]
            out["sources_used"].append("fmp")

    if av and not out["gainers"]:
        d = norm_alpha_vantage(_get_json(f"https://www.alphavantage.co/query?function=TOP_GAINERS_LOSERS&apikey={av}"))
        if d["gainers"] or d["losers"]:
            out["gainers"], out["losers"], out["most_active"] = d["gainers"][:TOP_N], d["losers"][:TOP_N], d["most_active"][:TOP_N]
            out["sources_used"].append("alpha_vantage")

    if poly and not out["gainers"]:
        g = norm_polygon(_get_json(f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/gainers?apiKey={poly}"), "polygon")
        l = norm_polygon(_get_json(f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/losers?apiKey={poly}"), "polygon")
        if g or l:
            out["gainers"], out["losers"] = g[:TOP_N], l[:TOP_N]
            out["sources_used"].append("polygon")

    if not out["gainers"]:  # no-key / all-failed fallback
        g = parse_stockanalysis_table(_get_text("https://stockanalysis.com/markets/gainers/") or "", "stockanalysis")
        l = parse_stockanalysis_table(_get_text("https://stockanalysis.com/markets/losers/") or "", "stockanalysis")
        if g or l:
            out["gainers"], out["losers"] = g, l
            out["sources_used"].append("stockanalysis")

    return out


def fetch_megacaps() -> Dict[str, Any]:
    fmp = os.environ.get("FMP_API_KEY")
    if fmp:
        url = ("https://financialmodelingprep.com/api/v3/stock-screener?"
               "marketCapMoreThan=50000000000&isActivelyTrading=true&limit=300&"
               f"exchange=NYSE,NASDAQ,AMEX&apikey={fmp}")
        rows = norm_fmp_screener(_get_json(url))
        if rows:
            return {"megacaps": rows, "source": "fmp_screener"}
    # fallback: stockanalysis biggest-companies (server-rendered)
    rows = parse_stockanalysis_table(_get_text("https://stockanalysis.com/list/biggest-companies/") or "", "stockanalysis")
    rows = [r for r in rows if r.get("market_cap")]
    rows.sort(key=lambda r: r["market_cap"] or 0, reverse=True)
    return {"megacaps": rows[:MEGACAP_N], "source": "stockanalysis" if rows else "none"}


# ── cross-reference against the system ──────────────────────────────
def _system_context(out: Path) -> Dict[str, set]:
    universe, debated, held = set(), set(), set()
    sig = _load(out / "signals.json", {})
    for d in (sig.get("debates") or []):
        t = str(d.get("ticker") or "").upper()
        if t:
            debated.add(t)
            universe.add(t)
    for u in (sig.get("universe", {}) or {}).get("tickers", []) if isinstance(sig.get("universe"), dict) else []:
        if isinstance(u, str):
            universe.add(u.upper())
    for f in ("alpaca_paper_state.json", "alpaca_h3_state.json", "alpaca_h5_state.json"):
        st = _load(out / f, {})
        for p in (st.get("positions_snapshot") or []):
            if isinstance(p, dict):
                s = p.get("symbol") or p.get("ticker")
                if s:
                    held.add(str(s).upper())
    return {"universe": universe, "debated": debated, "held": held}


def _annotate(rows: List[Dict[str, Any]], ctx: Dict[str, set]) -> List[Dict[str, Any]]:
    for r in rows:
        t = r["ticker"]
        r["in_universe"] = t in ctx["universe"]
        r["debated_today"] = t in ctx["debated"]
        r["held"] = t in ctx["held"]
        r["on_radar"] = r["in_universe"] or r["debated_today"] or r["held"]
    return rows


# ── orchestrator ────────────────────────────────────────────────────
def build_market_leaders(out_dir: Path) -> Dict[str, Any]:
    out = Path(out_dir)
    movers = fetch_movers()
    mega = fetch_megacaps()
    ctx = _system_context(out)

    gainers = _annotate(movers["gainers"], ctx)
    losers = _annotate(movers["losers"], ctx)
    actives = _annotate(movers["most_active"], ctx)
    megacaps = _annotate(mega["megacaps"], ctx)

    # leaders watchlist = strong gainers + megacaps, de-duped
    watch = _dedupe(gainers + megacaps)
    off_radar = [r["ticker"] for r in gainers if not r["on_radar"]][:15]

    sources = list(dict.fromkeys(movers["sources_used"] + ([mega["source"]] if mega.get("source") not in (None, "none") else [])))
    notes: List[str] = []
    if not sources:
        notes.append("No data source returned today. Set FMP_API_KEY (best), ALPHA_VANTAGE_API_KEY, "
                     "or POLYGON_API_KEY in repo secrets; the stockanalysis.com fallback needs outbound HTTP.")
    else:
        notes.append("Sources used: " + ", ".join(sources) + ".")
    if gainers:
        top = gainers[0]
        notes.append(f"Top gainer: {top['ticker']} {('%+.1f%%' % top['change_pct']) if top.get('change_pct') is not None else ''}"
                     + (" (on radar)" if top["on_radar"] else " — NOT on the system's radar"))
    if off_radar:
        notes.append(f"{len(off_radar)} of today's gainers are NOT in the system's universe/debates: "
                     + ", ".join(off_radar) + ". Candidate watchlist adds (gated).")

    payload = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources_used": sources,
        "counts": {"gainers": len(gainers), "losers": len(losers),
                   "most_active": len(actives), "megacaps": len(megacaps)},
        "gainers": gainers,
        "losers": losers,
        "most_active": actives,
        "megacaps": megacaps,
        "leaders_watchlist": [r["ticker"] for r in watch][:60],
        "gainers_off_radar": off_radar,
        "notes": notes,
    }
    _dump(out / "market_leaders.json", payload)
    return {"sources": sources, "gainers": len(gainers), "losers": len(losers),
            "megacaps": len(megacaps), "off_radar": len(off_radar)}


if __name__ == "__main__":  # pragma: no cover
    import sys
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")
    print(json.dumps(build_market_leaders(base), indent=2))
