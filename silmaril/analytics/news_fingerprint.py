"""
silmaril.analytics.news_fingerprint — each stock's news PERSONALITY, learned.

The thesis: the same headline does different things to different stocks. Some
names follow their news (a buy-signal day starts a multi-day run), some fade it
(the pop is sold by tomorrow), some ignore it entirely. And the horizon differs:
one stock is a 1-day reactor, another runs for 3 days, another grinds for a week.

This module learns that profile per stock, deterministically, from the system's
own daily observations — no LLM, no external service, no synthetic data:

  RECORD  Each cycle, store per ticker: date, sentiment, catalyst, dominant
          event, price (one row per day; the last cycle of the day wins).
  JOIN    Forward returns are computed against the SAME stock's later rows:
          +1, +3, +5 observed trading days.
  LEARN   On signal days (|sentiment| >= 0.30 or |catalyst| >= 0.5), measure the
          signal-aligned forward move: sign(signal) * forward_return. Averaged
          per horizon, that is the stock's follow-score: positive = follows its
          news, negative = fades it.
  PROFILE personality (news-follower / news-fader / news-immune), best horizon
          (1-day reactor / multi-day runner / week-long runner), and the average
          buy-signal and sell-signal reactions per horizon — the "what does this
          stock actually do when we get buy signals" answer, with sample sizes.

Output: docs/data/news_fingerprint.json. Confidence requires >= MIN_SIGNAL_DAYS
signal days; below that a name is marked learning and downstream consumers MUST
ignore it. Profiles are read by cli.py to scale how hard a decisive catalyst is
allowed to push the vote (followers: harder; faders: softer; never inverted).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "news-fingerprint-1.0"

MAX_ROWS_PER_TICKER = 150      # ~7 months of daily rows
MIN_SIGNAL_DAYS = 6            # signal days required before a profile is trusted
SENT_SIGNAL = 0.30             # |sentiment| at/above which a day counts as a signal day
CAT_SIGNAL = 0.50              # |catalyst| at/above which a day counts as a signal day
FOLLOW_PCT = 0.25              # avg aligned move (pct) to call follower/fader
HORIZONS = (1, 3, 5)
HORIZON_LABEL = {1: "1-day reactor", 3: "multi-day runner", 5: "week-long runner"}


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def _sanitize(o: Any) -> Any:
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _sanitize(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_sanitize(v) for v in o]
    return o


def _dump(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(_sanitize(obj), f, indent=2, allow_nan=False)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ── recording ────────────────────────────────────────────────────────
def record_news_day(data_dir: Path, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Append/refresh today's per-ticker news row from signals.json. One row per
    (ticker, date); the latest cycle of the day overwrites so the row reflects
    the day's final read."""
    now = now or datetime.now(timezone.utc)
    # ET trading date (EDT in June = UTC-4): a 03:14 UTC run is still the
    # PREVIOUS trading day's evening — recording it under the UTC date created
    # phantom day-rollovers and 0.0% deltas.
    from datetime import timedelta as _td
    date = (now + _td(hours=-4)).strftime("%Y-%m-%d")
    sig = _load(data_dir / "signals.json", {})
    hist = _load(data_dir / "news_history.json", {})
    if not isinstance(hist, dict):
        hist = {}
    n = 0
    for d in (sig.get("debates") or []):
        t = str(d.get("ticker") or "").upper()
        px = d.get("price")
        if not t or not isinstance(px, (int, float)) or px <= 0:
            continue
        row = {
            "date": date,
            "price": float(px),
            "sent": round(float(d.get("sentiment_score") or 0.0), 4),
            "cat": d.get("news_catalyst"),
            "cat_label": d.get("news_catalyst_label"),
            "antic": _anticipation_of(d),
            "ipo": d.get("ipo_phase"),
            "event": _dominant_event(d),
            "signal": (d.get("consensus") or {}).get("signal"),
        }
        rows = hist.setdefault(t, [])
        if rows and rows[-1].get("date") == date:
            row["open_read"] = (rows[-1].get("open_read")
                                or rows[-1].get("price"))
            rows[-1] = row
        else:
            row["open_read"] = row.get("price")
            rows.append(row)
        if len(rows) > MAX_ROWS_PER_TICKER:
            del rows[: len(rows) - MAX_ROWS_PER_TICKER]
        n += 1
    _dump(data_dir / "news_history.json", hist)
    return {"recorded": n, "date": date}


def _anticipation_of(d: Dict[str, Any]) -> float:
    """Day's forward-looking score for a ticker, from its headlines. Word-based
    prediction fuel: expectation language, distinct from happened-language."""
    try:
        from .sentiment import anticipation_score
    except Exception:
        return 0.0
    vals = []
    for h in (d.get("recent_headlines") or []):
        a = anticipation_score(str((h or {}).get("title") or ""))
        if a:
            vals.append(a)
    return round(sum(vals) / len(vals), 3) if vals else 0.0


def _dominant_event(d: Dict[str, Any]) -> Optional[str]:
    counts: Dict[str, int] = {}
    for h in (d.get("recent_headlines") or []):
        for ev in (h or {}).get("events") or []:
            counts[ev] = counts.get(ev, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0] if counts else None


# ── profiling ────────────────────────────────────────────────────────
def _profile_one(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    rows = sorted(rows, key=lambda r: r.get("date", ""))
    if len(rows) < 3:
        return None
    # forward returns (pct) per row per horizon, by observed-day offset
    buy = {h: [] for h in HORIZONS}    # aligned moves on positive-signal days
    sell = {h: [] for h in HORIZONS}   # aligned moves on negative-signal days
    follow = {h: [] for h in HORIZONS}  # sign(signal)*fwd for all signal days
    n_signal_days = 0
    for i, r in enumerate(rows):
        sent = r.get("sent") or 0.0
        cat = r.get("cat")
        strength = cat if (cat is not None and abs(cat) >= CAT_SIGNAL) else (
            sent if abs(sent) >= SENT_SIGNAL else None)
        if strength is None or r.get("price") in (None, 0):
            continue
        n_signal_days += 1
        sgn = 1.0 if strength > 0 else -1.0
        for h in HORIZONS:
            j = i + h
            if j < len(rows) and rows[j].get("price"):
                fwd = (rows[j]["price"] - r["price"]) / r["price"] * 100.0
                follow[h].append(sgn * fwd)
                (buy if sgn > 0 else sell)[h].append(fwd)
    if n_signal_days == 0:
        return None

    def _avg(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    fscores = {h: _avg(follow[h]) for h in HORIZONS}
    usable = {h: s for h, s in fscores.items() if s is not None and len(follow[h]) >= 3}
    best_h, best_s = (max(usable.items(), key=lambda kv: abs(kv[1])) if usable else (None, None))
    learning = n_signal_days < MIN_SIGNAL_DAYS or best_h is None
    if learning or best_s is None:
        personality = "learning"
    elif best_s >= FOLLOW_PCT:
        personality = "news-follower"
    elif best_s <= -FOLLOW_PCT:
        personality = "news-fader"
    else:
        personality = "news-immune"

    note = None
    if not learning:
        if personality == "news-follower":
            note = (f"follows its news — signal days have run "
                    f"{best_s:+.2f}% (aligned) over {best_h}d")
        elif personality == "news-fader":
            note = (f"fades its news — signal-day moves reverse "
                    f"{best_s:+.2f}% (aligned) by {best_h}d; chasing headlines here has lost")
        else:
            note = "news lands flat — headlines have not predicted its next moves"

    return {
        "n_rows": len(rows),
        "n_signal_days": n_signal_days,
        "learning": learning,
        "personality": personality,
        "best_horizon_days": best_h,
        "best_horizon": HORIZON_LABEL.get(best_h) if best_h else None,
        "follow_score_pct": best_s,
        "follow_by_horizon": fscores,
        "buy_reaction_pct": {str(h): _avg(buy[h]) for h in HORIZONS},
        "buy_n": {str(h): len(buy[h]) for h in HORIZONS},
        "sell_reaction_pct": {str(h): _avg(sell[h]) for h in HORIZONS},
        "sell_n": {str(h): len(sell[h]) for h in HORIZONS},
        "note": note,
    }


def compute_news_fingerprints(data_dir: Path) -> Dict[str, Any]:
    hist = _load(data_dir / "news_history.json", {})
    if not isinstance(hist, dict):
        hist = {}
    profiles: Dict[str, Any] = {}
    confident = 0
    deltas: Dict[str, Any] = {}
    for t, rows in hist.items():
        rs = sorted(rows, key=lambda r: r.get("date", ""))
        if len(rs) >= 2 and rs[-1].get("price") and rs[-2].get("price"):
            prev, last = rs[-2]["price"], rs[-1]["price"]
            deltas[t] = {"prev_price": prev, "last_price": last,
                         "prev_date": rs[-2].get("date"),
                         "pct_since_prev": round((last - prev) / prev * 100.0, 2)}
            _op = rs[-1].get("open_read")
            if _op and _op > 0 and _op != last:
                deltas[t]["pct_today"] = round((last - _op) / _op * 100.0, 2)
            try:
                from datetime import date as _D
                _y, _w, _ = _D.fromisoformat(rs[-1]["date"]).isocalendar()
                _wk = [r for r in rs if r.get("price")
                       and _D.fromisoformat(r["date"]).isocalendar()[:2]
                       == (_y, _w)]
                if len(_wk) >= 2 and _wk[0]["price"]:
                    deltas[t]["pct_wtd"] = round(
                        (last - _wk[0]["price"]) / _wk[0]["price"] * 100.0, 2)
            except Exception:
                pass
        p = _profile_one(rows)
        if p:
            profiles[t] = p
            if not p["learning"]:
                confident += 1
    payload = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tickers_tracked": len(profiles),
        "tickers_confident": confident,
        "min_signal_days": MIN_SIGNAL_DAYS,
        "deltas": deltas,
        "fingerprints": profiles,
    }
    _dump(data_dir / "news_fingerprint.json", payload)
    return {"tracked": len(profiles), "confident": confident}


def build_news_fingerprint(data_dir: Path, now: Optional[datetime] = None) -> Dict[str, Any]:
    rec = record_news_day(data_dir, now)
    comp = compute_news_fingerprints(data_dir)
    return {"recorded": rec["recorded"], "tracked": comp["tracked"],
            "confident": comp["confident"]}


if __name__ == "__main__":  # pragma: no cover
    import sys
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")
    print(json.dumps(build_news_fingerprint(base), indent=2))
