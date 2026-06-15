"""
silmaril.analytics.timing_fingerprint — each stock's clock, learned.

The thesis: a stock's best entry/exit time is not a fixed clock — it's the
stock's own repeating rhythm (when it tends to bottom and top intraday, where
its floor and ceiling sit). We can't get that from one snapshot, so we LEARN it:
every cycle (the suite runs ~every 15 min during market hours) we record each
stock's price and time-of-day. Over days, per time-of-day bucket, we measure
where in that day's range the stock sat — revealing its typical cheap window
(buy) and rich window (sell). Floors/ceilings come from the accumulated range.

Pure, deterministic, additive. No LLM, no external call. Writes:
  - timing_history.json     (rolling raw observations, capped per ticker)
  - timing_fingerprint.json  (the learned per-stock fingerprint + a now-signal)

Confidence grows with data: a fingerprint stays "learning" until it has seen a
ticker on >= MIN_DAYS distinct days. Nothing here touches trading or scoring —
it is intelligence to read now and wire into entry/exit timing once it has
enough clean days (the same clean-data discipline as the rest of the system).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

VERSION = "timing-fingerprint-1.0"

# June = US Eastern Daylight Time = UTC-4. Regular session 09:30–16:00 ET.
ET_OFFSET_HOURS = -4
MARKET_OPEN_MIN = 9 * 60 + 30      # 09:30 ET in minutes
MARKET_CLOSE_MIN = 16 * 60         # 16:00 ET
BUCKET_MIN = 30                    # 30-minute time-of-day buckets

MAX_OBS_PER_TICKER = 800           # rolling cap
MIN_DAYS = 3                       # days of data before a confident window
RANGE_LOOKBACK_DAYS = 20           # floor/ceiling window
# ── predictive bootstrap (Alpha 6.4) ─────────────────────────────────
# Self-recorded history needs weeks to mature; real intraday history
# already exists. We seed each clock from 60 days of 30-minute bars so
# best-buy/best-sell windows and floor/ceiling bands are predictive NOW,
# then let live self-recorded observations keep refining them.
BOOT_PERIOD = "60d"
BOOT_INTERVAL = "30m"
BOOT_MIN_DAYS = 15                 # bar-days needed for a confident bootstrap
BOOT_REFRESH_DAYS = 5              # re-fetch a ticker's bars after this many days
BOOT_MAX_FETCH_PER_RUN = 40        # be polite to the data source; rotate coverage


# ── io ──────────────────────────────────────────────────────────────
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


# ── time helpers ─────────────────────────────────────────────────────
def _et(now: datetime) -> datetime:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc) + timedelta(hours=ET_OFFSET_HOURS)


def _tod_bucket(now: datetime) -> Optional[str]:
    """30-min ET bucket label like '09:30', '10:00'. None if outside session."""
    et = _et(now)
    mins = et.hour * 60 + et.minute
    if mins < MARKET_OPEN_MIN or mins > MARKET_CLOSE_MIN:
        return None
    b = (mins // BUCKET_MIN) * BUCKET_MIN
    return f"{b // 60:02d}:{b % 60:02d}"


# ── recording ────────────────────────────────────────────────────────
def record_observation(data_dir: Path, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Append this cycle's per-ticker price to timing_history.json, bucketed by
    ET time-of-day. Deduped per (date, bucket): the latest price in a bucket wins.
    Skips silently outside the regular session (so after-hours noise is ignored)."""
    now = now or datetime.now(timezone.utc)
    bucket = _tod_bucket(now)
    if bucket is None:
        return {"recorded": 0, "reason": "outside session"}
    date = _et(now).strftime("%Y-%m-%d")

    sig = _load(data_dir / "signals.json", {})
    hist = _load(data_dir / "timing_history.json", {})
    if not isinstance(hist, dict):
        hist = {}

    recorded = 0
    for d in (sig.get("debates") or []):
        t = str(d.get("ticker") or "").upper()
        px = d.get("price")
        if not t or not isinstance(px, (int, float)) or px <= 0:
            continue
        obs = hist.setdefault(t, [])
        if obs and obs[-1].get("date") == date and obs[-1].get("tod") == bucket:
            obs[-1]["price"] = float(px)        # update bucket
        else:
            obs.append({"date": date, "tod": bucket, "price": float(px)})
        if len(obs) > MAX_OBS_PER_TICKER:
            del obs[: len(obs) - MAX_OBS_PER_TICKER]
        recorded += 1

    _dump(data_dir / "timing_history.json", hist)
    return {"recorded": recorded, "date": date, "bucket": bucket}


# ── fingerprint computation ──────────────────────────────────────────
def _fingerprint_one(obs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if len(obs) < 4:
        return None
    by_day: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for o in obs:
        by_day[o["date"]].append(o)

    # position-in-range per observation, accumulated per tod bucket
    bucket_pos: Dict[str, List[float]] = defaultdict(list)
    for day, rows in by_day.items():
        prices = [r["price"] for r in rows]
        lo, hi = min(prices), max(prices)
        rng = hi - lo
        if rng <= 0:
            continue
        for r in rows:
            bucket_pos[r["tod"]].append((r["price"] - lo) / rng)

    n_days = len(by_day)
    buckets = {b: round(sum(v) / len(v), 3) for b, v in bucket_pos.items() if v}
    learning = n_days < MIN_DAYS or len(buckets) < 3

    best_buy = min(buckets.items(), key=lambda kv: kv[1]) if buckets else None
    best_sell = max(buckets.items(), key=lambda kv: kv[1]) if buckets else None

    # recent floor/ceiling over the lookback window of daily lows/highs
    days_sorted = sorted(by_day.keys())[-RANGE_LOOKBACK_DAYS:]
    day_lows = [min(r["price"] for r in by_day[d]) for d in days_sorted]
    day_highs = [max(r["price"] for r in by_day[d]) for d in days_sorted]
    floor = round(min(day_lows), 2) if day_lows else None
    ceiling = round(max(day_highs), 2) if day_highs else None

    # today's state
    today = days_sorted[-1] if days_sorted else None
    today_rows = by_day.get(today, [])
    cur_price = today_rows[-1]["price"] if today_rows else None
    cur_tod = today_rows[-1]["tod"] if today_rows else None
    t_lo = min((r["price"] for r in today_rows), default=None)
    t_hi = max((r["price"] for r in today_rows), default=None)
    cur_pos = None
    if cur_price is not None and t_hi is not None and t_hi > t_lo:
        cur_pos = round((cur_price - t_lo) / (t_hi - t_lo), 3)

    # floor/ceiling position over the whole window
    band_pos = None
    if cur_price is not None and ceiling and floor is not None and ceiling > floor:
        band_pos = round((cur_price - floor) / (ceiling - floor), 3)

    note = "learning — needs more days"
    if not learning and cur_pos is not None:
        loc = ("lower third — historically a buy-favorable spot" if cur_pos <= 0.34
               else "upper third — historically a sell-favorable spot" if cur_pos >= 0.66
               else "mid-range")
        tod_hint = ""
        if best_buy and cur_tod == best_buy[0]:
            tod_hint = " · now is this stock's typical daily low window"
        elif best_sell and cur_tod == best_sell[0]:
            tod_hint = " · now is this stock's typical daily high window"
        note = f"in the {loc} of today's range{tod_hint}"

    return {
        "n_days": n_days,
        "n_obs": len(obs),
        "learning": learning,
        "best_buy_window": (best_buy[0] if best_buy else None),
        "best_buy_pos": (best_buy[1] if best_buy else None),
        "best_sell_window": (best_sell[0] if best_sell else None),
        "best_sell_pos": (best_sell[1] if best_sell else None),
        "tod_curve": dict(sorted(buckets.items())),
        "floor": floor,
        "ceiling": ceiling,
        "current_price": cur_price,
        "current_tod": cur_tod,
        "today_pos_in_range": cur_pos,
        "band_pos": band_pos,
        "note": note,
    }


def _fetch_bars_yf(ticker: str) -> Optional[List[Dict[str, Any]]]:
    """60d of 30m bars -> observation rows. None on ANY failure (offline-safe)."""
    try:
        import yfinance as yf  # available in Actions; absent locally is fine
        df = yf.Ticker(ticker).history(period=BOOT_PERIOD,
                                       interval=BOOT_INTERVAL, prepost=False)
        if df is None or df.empty:
            return None
        obs: List[Dict[str, Any]] = []
        for ts, row in df.iterrows():
            try:
                t = ts.tz_convert("America/New_York") if ts.tzinfo else ts
                hhmm = t.hour * 60 + t.minute
                if hhmm < 570 or hhmm >= 960:      # regular session only
                    continue
                mins = (t.minute // 30) * 30
                obs.append({"date": t.strftime("%Y-%m-%d"),
                            "tod": f"{t.hour:02d}:{mins:02d}",
                            "price": float(row["Close"])})
            except Exception:
                continue
        return obs or None
    except Exception:
        return None


def bootstrap_fingerprints(data_dir: Path,
                           tickers: List[str]) -> Dict[str, Dict[str, Any]]:
    """Maintain a cache of bar-seeded fingerprints; refresh a polite slice per
    run. Returns {ticker: confident_fingerprint}. Fully offline-safe."""
    cache_path = data_dir / "timing_bootstrap.json"
    cache = _load(cache_path, {})
    if not isinstance(cache, dict):
        cache = {}
    now = datetime.now(timezone.utc)
    # prioritize what the desk is actually debating/holding today
    priority: List[str] = []
    try:
        sig = _load(data_dir / "signals.json", {})
        priority = [str(d.get("ticker")) for d in (sig.get("debates") or [])]
    except Exception:
        pass
    ordered = [t for t in priority if t in tickers]
    ordered += [t for t in sorted(tickers) if t not in ordered]

    fetched = 0
    for t in ordered:
        if fetched >= BOOT_MAX_FETCH_PER_RUN:
            break
        ent = cache.get(t) or {}
        try:
            age_ok = ent.get("fetched_at") and (
                (now - datetime.fromisoformat(ent["fetched_at"])).days
                < BOOT_REFRESH_DAYS)
        except Exception:
            age_ok = False
        if age_ok:
            continue
        bars = _fetch_bars_yf(t)
        if not bars:
            continue
        fetched += 1
        fp = _fingerprint_one(bars)
        if not fp or fp["n_days"] < BOOT_MIN_DAYS:
            continue
        fp["learning"] = False
        fp["source"] = f"bars{BOOT_PERIOD}"
        fp["note"] = (f"seeded from {fp['n_days']} bar-days — floor/ceiling = "
                      f"last {RANGE_LOOKBACK_DAYS} sessions")
        cache[t] = {"fetched_at": now.isoformat(), "fingerprint": fp}
    if fetched:
        _dump(cache_path, cache)
    out: Dict[str, Dict[str, Any]] = {}
    for t, ent in cache.items():
        fp = (ent or {}).get("fingerprint")
        if fp and not fp.get("learning", True):
            out[t] = fp
    return out


def compute_fingerprints(data_dir: Path) -> Dict[str, Any]:
    hist = _load(data_dir / "timing_history.json", {})
    if not isinstance(hist, dict):
        hist = {}
    prints: Dict[str, Any] = {}
    confident = 0
    for t, obs in hist.items():
        fp = _fingerprint_one(obs)
        if fp:
            prints[t] = fp
            if not fp["learning"]:
                confident += 1
    # merge bar-seeded clocks wherever self-history is still learning,
    # keeping live today-state from self-recorded observations
    try:
        boot = bootstrap_fingerprints(data_dir, list(hist.keys()))
    except Exception:
        boot = {}
    for t, bfp in boot.items():
        cur = prints.get(t)
        if cur is None or cur.get("learning", True):
            merged = dict(bfp)
            if cur:
                for k in ("current_price", "current_tod", "today_pos_in_range"):
                    if cur.get(k) is not None:
                        merged[k] = cur[k]
            else:
                # thin self-history (<4 obs) still has a live last observation
                rows = hist.get(t) or []
                if rows:
                    merged["current_price"] = rows[-1].get("price")
                    merged["current_tod"] = rows[-1].get("tod")
            cp, fl, ce = (merged.get("current_price"),
                          merged.get("floor"), merged.get("ceiling"))
            if cp and fl is not None and ce and ce > fl:
                merged["band_pos"] = round((cp - fl) / (ce - fl), 3)
            prints[t] = merged
    confident = sum(1 for v in prints.values() if not v.get("learning", True))
    payload = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tickers_tracked": len(prints),
        "tickers_confident": confident,
        "min_days_for_confidence": MIN_DAYS,
        "fingerprints": prints,
    }
    _dump(data_dir / "timing_fingerprint.json", payload)
    return {"tracked": len(prints), "confident": confident}


def build_timing(data_dir: Path, now: Optional[datetime] = None) -> Dict[str, Any]:
    rec = record_observation(data_dir, now)
    comp = compute_fingerprints(data_dir)
    return {"recorded": rec.get("recorded", 0), "bucket": rec.get("bucket"),
            "tracked": comp["tracked"], "confident": comp["confident"]}


if __name__ == "__main__":  # pragma: no cover
    import sys
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")
    print(json.dumps(build_timing(base), indent=2))
