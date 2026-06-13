"""
silmaril.analytics.valuables — ALL valuables, same treatment (Alpha 0.007).

The founding vision: not just stocks — gold, oil, crypto, the metals, the
macro tape — every valuable judged by the same word engine, recorded in the
same history shape, eligible for the same fingerprints and judgement. This
module is the ingestion organ: it does NOT trade (Alpaca stays stocks-only);
it watches, scores, records — so the day an output platform exists, years of
graded valuables history already will.

Registry: BTC ETH SOL (crypto) · GC=F gold · SI=F silver · CL=F WTI ·
NG=F natgas · HG=F copper · DX-Y.NYB dollar index. Prices + headlines via
yfinance (already a project dependency), titles scored by OUR sentiment +
anticipation + catalysts, rows appended to valuables_history.json in the
EXACT news_history shape {date, price, sent, cat, cat_label, antic, event}
so news_fingerprint-style personality profiling can ride the same code later.
Offline-safe (sandbox keeps stored data untouched), fetcher injectable.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

REGISTRY = (
    ("BTC",    "BTC-USD",  "Bitcoin"),
    ("ETH",    "ETH-USD",  "Ethereum"),
    ("SOL",    "SOL-USD",  "Solana"),
    ("GOLD",   "GC=F",     "Gold futures"),
    ("SILVER", "SI=F",     "Silver futures"),
    ("OIL",    "CL=F",     "WTI crude"),
    ("NATGAS", "NG=F",     "Natural gas"),
    ("COPPER", "HG=F",     "Copper"),
    ("DXY",    "DX-Y.NYB", "US dollar index"),
)
CAP_ROWS = 1500


def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _yf_snapshot(yf_symbol: str) -> Optional[Dict[str, Any]]:
    try:
        import yfinance as yf
        t = yf.Ticker(yf_symbol)
        h = t.history(period="5d", interval="1d")
        if h is None or len(h) == 0:
            return None
        px = float(h["Close"].iloc[-1])
        prev = float(h["Close"].iloc[-2]) if len(h) > 1 else px
        titles = []
        try:
            for n in (t.news or [])[:8]:
                ti = str((n or {}).get("title") or "").strip()
                if ti:
                    titles.append(ti[:160])
        except Exception:
            pass
        return {"price": px, "chg_1d_pct": round((px / prev - 1) * 100, 2),
                "titles": titles}
    except Exception:
        return None


def build_valuables(out_dir: str, fetcher=None) -> Dict[str, Any]:
    out = Path(out_dir)
    hist: Dict[str, List[dict]] = _load(out / "valuables_history.json", {})
    if not isinstance(hist, dict):
        hist = {}
    prev = _load(out / "valuables_pulse.json", {})
    now = datetime.now(timezone.utc)
    date = (now + timedelta(hours=-4)).strftime("%Y-%m-%d")

    def _imp(name, fallback):
        try:
            from . import sentiment as _S
            return getattr(_S, name)
        except Exception:
            return fallback
    score_text = _imp("score_text", lambda t: 0.0)
    anticipation_score = _imp("anticipation_score", lambda t: 0.0)
    _dc = _imp("detect_decisive_catalyst",
               _imp("detect_catalyst", lambda ts: (None, None)))
    def detect_catalyst(ts):
        try:
            r = _dc(ts)
            return (r[0], r[1]) if isinstance(r, (tuple, list)) and len(r) >= 2 \
                else (None, None)
        except Exception:
            return (None, None)
    _de = _imp("detect_event", _imp("detect_event_tag", lambda t: None))
    def detect_event(t):
        try:
            return _de(t)
        except Exception:
            return None

    board: Dict[str, Any] = {}
    fetched = 0
    for tag, sym, label in REGISTRY:
        snap = fetcher(sym) if fetcher is not None else _yf_snapshot(sym)
        if snap is None:
            keep = (prev.get("valuables") or {}).get(tag)
            if keep:
                board[tag] = {**keep, "stale": True}
            continue
        fetched += 1
        titles = snap.get("titles") or []
        scores = [float(score_text(t)) for t in titles]
        sent = round(sum(scores) / len(scores), 3) if scores else 0.0
        antic = round(sum(float(anticipation_score(t)) for t in titles)
                      / len(titles), 3) if titles else 0.0
        try:
            cat, cat_label = detect_catalyst(titles)
        except Exception:
            cat, cat_label = None, None
        event = None
        for t in titles:
            try:
                event = event or detect_event(t)
            except Exception:
                break
        board[tag] = {"label": label, "yf": sym,
                      "price": round(snap["price"], 4),
                      "chg_1d_pct": snap["chg_1d_pct"],
                      "sent": sent, "antic": antic,
                      "cat_label": cat_label, "event": event,
                      "articles": len(titles),
                      "top_title": (titles[0] if titles else None)}
        rows = hist.setdefault(tag, [])
        if not rows or rows[-1].get("date") != date:
            rows.append({"date": date, "price": round(snap["price"], 4),
                         "sent": sent, "cat": cat, "cat_label": cat_label,
                         "antic": antic, "ipo": None, "event": event,
                         "signal": None})
        else:
            rows[-1].update({"price": round(snap["price"], 4), "sent": sent,
                             "antic": antic})
        try:
            from .archive import archive_then_trim
            hist[tag] = archive_then_trim(out, "valuables_history",
                                          rows, CAP_ROWS)
        except Exception:
            hist[tag] = rows[-CAP_ROWS:]

    if board:
        (out / "valuables_history.json").write_text(json.dumps(hist))
        (out / "valuables_pulse.json").write_text(json.dumps({
            "generated_at": now.isoformat(),
            "valuables": board,
            "note": ("same words, same judgement, same permanent record — "
                     "output platforms come later; the history starts now"),
            "fetch_ok": fetched,
        }, indent=2))
    return {"tracked": len(board), "fetch_ok": fetched,
            "days_recorded": max((len(v) for v in hist.values()),
                                 default=0)}
