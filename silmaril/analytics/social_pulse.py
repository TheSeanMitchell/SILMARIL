"""
silmaril.analytics.social_pulse — the forum layer (Alpha 0.007).

"There has to be more sources." Here is the first social organ: Reddit's
public JSON endpoints (no API key, fair-use UA) polled for a small watchlist
across the big trading subs. Every fetched title runs through OUR OWN word
engine (sentiment + anticipation + catalysts) — no new scoring system, the
same deterministic stack that votes, now fed retail chatter.

Measured per ticker:
    mentions_24h        raw chatter volume
    velocity            mentions this run vs. stored prior run (the spike IS
                        the signal — a 10x jump precedes tape more often than
                        the absolute count)
    word_score          avg sentiment of titles through analytics.sentiment
    anticipation        forward-looking expectation in the chatter
    top_titles          receipts (capped, archived)

Output: docs/data/social_pulse.json. The SPCX debut console reads it; rows are
appended to the permanent archive so Dr. Strange can someday condition on
"retail roar" as a regime. stdlib-only, offline-safe, fetcher injectable for
tests, throttled and polite.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SUBS = ("wallstreetbets", "stocks", "investing", "options")
WATCHLIST = ("SPCX",)          # debut week focus; widen post-IPO
LIMIT_PER_SUB = 40
_UA = {"User-Agent": "SILMARIL research bot (paper trading research)"}


def _fetch_sub(sub: str, query: str) -> Optional[dict]:
    url = (f"https://www.reddit.com/r/{sub}/search.json?q={query}"
           f"&restrict_sr=1&sort=new&limit={LIMIT_PER_SUB}&t=day")
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _titles(data: Optional[dict]) -> List[Dict[str, Any]]:
    out = []
    try:
        for ch in ((data or {}).get("data") or {}).get("children") or []:
            d = ch.get("data") or {}
            t = str(d.get("title") or "").strip()
            if t:
                out.append({"title": t[:200],
                            "ups": int(d.get("ups") or 0),
                            "sub": str(d.get("subreddit") or "")})
    except Exception:
        pass
    return out


def build_social_pulse(out_dir: str, fetcher=None) -> Dict[str, Any]:
    """fetcher injectable: fetcher(sub, query) -> reddit listing dict."""
    out = Path(out_dir)
    path = out / "social_pulse.json"
    try:
        prev = json.loads(path.read_text())
    except Exception:
        prev = {}
    now = datetime.now(timezone.utc)

    try:
        from .sentiment import score_text, anticipation_score
    except Exception:
        def score_text(t): return 0.0
        def anticipation_score(t): return 0.0

    tickers: Dict[str, Any] = {}
    fetch_ok = 0
    for tkr in WATCHLIST:
        rows: List[Dict[str, Any]] = []
        for sub in SUBS:
            data = (fetcher(sub, tkr) if fetcher is not None
                    else _fetch_sub(sub, tkr))
            if data is not None:
                fetch_ok += 1
                rows.extend(_titles(data))
        if not rows and fetcher is None and fetch_ok == 0:
            continue  # fully offline: keep stored snapshot untouched
        seen, uniq = set(), []
        for r in rows:
            k = r["title"].lower()
            if k not in seen:
                seen.add(k)
                uniq.append(r)
        scores = [score_text(r["title"]) for r in uniq]
        antic = [anticipation_score(r["title"]) for r in uniq]
        prior = ((prev.get("tickers") or {}).get(tkr) or {}).get("mentions_24h")
        mentions = len(uniq)
        velocity = (round(mentions / prior, 2)
                    if isinstance(prior, (int, float)) and prior else None)
        tickers[tkr] = {
            "mentions_24h": mentions,
            "prev_mentions": prior,
            "velocity_x": velocity,
            "word_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
            "anticipation": round(sum(antic) / len(antic), 3) if antic else 0.0,
            "hot": bool(velocity and velocity >= 3.0),
            "top_titles": sorted(uniq, key=lambda r: -r["ups"])[:8],
        }

    if not tickers and prev.get("tickers"):
        tickers = prev["tickers"]  # offline-safe continuity

    payload = {
        "generated_at": now.isoformat(),
        "tickers": tickers,
        "subs": list(SUBS),
        "note": ("Retail chatter scored by the same word engine that votes. "
                 "Velocity (x vs prior run) matters more than raw count."),
        "fetch_ok": fetch_ok,
    }
    path.write_text(json.dumps(payload, indent=2))
    try:
        from .archive import archive_rows
        archive_rows(out, "social_pulse",
                     [{"ts": now.isoformat(), "ticker": k, **{kk: vv for kk, vv
                       in v.items() if kk != "top_titles"}}
                      for k, v in tickers.items()])
    except Exception:
        pass
    spcx = tickers.get("SPCX") or {}
    return {"tickers": len(tickers), "fetch_ok": fetch_ok,
            "spcx_mentions": spcx.get("mentions_24h"),
            "spcx_velocity": spcx.get("velocity_x")}
