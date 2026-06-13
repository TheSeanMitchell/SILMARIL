"""
silmaril.learning.sentiment_ledger — Does the news actually predict the move?

This is the missing calibration layer for "edge in words". The raw lexicon
sentiment (silmaril.analytics.sentiment) produces a score in [-1, +1] per
ticker per cycle. That score *feeds agent votes* today — but nothing has ever
graded whether a given sentiment reading was a LEGIT signal or just OVERHYPE.
This module builds that grade, and it grows with every run.

WHY FORWARD-ONLY (the honest constraint):
    sentiment_score was only persisted into signals.json recently. No historical
    run carries it (verified: 0/36 runs in history.json). So we cannot fabricate
    a backfill. Instead the ledger ACCUMULATES: each cycle it records the day's
    per-ticker sentiment, and on later cycles it grades those entries against the
    realized return the scoring pipeline already computed (scoring.json outcomes),
    joined on (ticker, date). That reuses the clean, deduped, stale-flagged return
    that already drives learning — no second price fetch, no new contamination.

WHAT IT ANSWERS, over hour / day / week:
    • For each sentiment bin (very_neg ... very_pos), what is the realized forward
      return, the hit-rate, and a t-stat — so we know which readings are tradeable.
    • OVERHYPE rate: of strongly-positive-sentiment names, how many actually fell.
    • LEGIT rate: of strongly-positive-sentiment names, how many actually rose.
    • Realized-horizon cuts (1d / 2-5d / 6d+) from the actual scoring lag, so the
      "over the hour/day/week/month" view is real, not assumed.
    • Responsiveness (immediate, present-data): how strongly today's sentiment is
      already moving consensus — proves the wiring without waiting for grades.

It writes two files:
    sentiment_ledger.json       the accumulating store (one row per ticker/day)
    sentiment_calibration.json  the dashboard scorecard built from graded rows

Read-only with respect to trading and scoring. Safe to run every cycle.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from ..analytics.sentiment import score_text  # reuse the REAL scorer
except Exception:  # pragma: no cover - module should always import
    def score_text(_t: str) -> float:  # type: ignore
        return 0.0

# ── tuning ──────────────────────────────────────────────────────────
LEDGER_VERSION = "sentiment-ledger-1.0"
MAX_LEDGER_ROWS = 20000          # generous; user OK with growth/migration
MIN_N_BIN = 8                    # below this a bin verdict is "thin"
STRONG_POS = 0.5                 # threshold for "strongly positive" sentiment
STRONG_NEG = -0.5

# Sentiment bins (lower-inclusive). Order matters for display.
BINS: List[Tuple[str, float, float]] = [
    ("very_neg", -1.0001, -0.5),
    ("neg",      -0.5,     -0.1),
    ("neutral",  -0.1,      0.1),
    ("pos",       0.1,      0.5),
    ("very_pos",  0.5,      1.0001),
]

_BUY = {"BUY", "STRONG_BUY"}
_SELL = {"SELL", "STRONG_SELL"}


# ── small io helpers (atomic, NaN-safe) ─────────────────────────────
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
        return json.loads(path.read_text())
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


def _bin_of(score: Optional[float]) -> str:
    if score is None:
        return "neutral"
    s = float(score)
    for name, lo, hi in BINS:
        if lo <= s < hi:
            return name
    return "very_pos" if s > 0 else "very_neg"


def _date_of(iso: Optional[str]) -> str:
    if not iso:
        return ""
    return str(iso)[:10]


def _days_between(a: str, b: str) -> Optional[int]:
    try:
        da = datetime.fromisoformat(a[:10]).date()
        db = datetime.fromisoformat(b[:10]).date()
        return (db - da).days
    except Exception:
        return None


def _stats(xs: List[float]) -> Dict[str, Any]:
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean_return": 0.0, "hit_rate": 0.0, "t_stat": 0.0, "verdict": "none"}
    mean = sum(xs) / n
    sd = (sum((x - mean) ** 2 for x in xs) / n) ** 0.5 if n > 1 else 0.0
    t = (mean / (sd / math.sqrt(n))) if sd > 0 else 0.0
    hit = sum(1 for x in xs if x > 0) / n
    if n < MIN_N_BIN:
        verdict = "thin"
    elif abs(t) > 2.0:
        verdict = "significant"
    elif abs(t) > 1.5:
        verdict = "suggestive"
    else:
        verdict = "none"
    return {
        "n": n,
        "mean_return": round(mean, 4),
        "hit_rate": round(hit, 4),
        "t_stat": round(t, 3),
        "verdict": verdict,
    }


def _pearson(pairs: List[Tuple[float, float]]) -> Optional[float]:
    n = len(pairs)
    if n < 3:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return round(sxy / math.sqrt(sxx * syy), 4)


# ── step 1: record the day's sentiment snapshot ─────────────────────
def record_cycle_snapshot(ledger: Dict[str, Any], signals: Dict[str, Any]) -> int:
    """Append one row per debated ticker for today's run. Idempotent on
    (date, ticker) so re-runs in the same day don't double-count."""
    rows: List[Dict[str, Any]] = ledger.setdefault("rows", [])
    seen = {(r.get("date"), r.get("ticker")) for r in rows}
    run_date = _date_of((signals.get("meta") or {}).get("generated_at"))
    recorded_at = (signals.get("meta") or {}).get("generated_at") or \
        datetime.now(timezone.utc).isoformat()
    added = 0
    for d in signals.get("debates", []) or []:
        tkr = d.get("ticker")
        if not tkr or (run_date, tkr) in seen:
            continue
        sent = d.get("sentiment_score")
        # Recompute from headlines if missing but headlines exist — never invent.
        if sent is None and d.get("recent_headlines"):
            titles = [h.get("title", "") for h in d["recent_headlines"] if isinstance(h, dict)]
            scored = [score_text(t) for t in titles if t]
            sent = (sum(scored) / len(scored)) if scored else None
        cons = d.get("consensus") or {}
        rows.append({
            "date": run_date,
            "recorded_at": recorded_at,
            "ticker": tkr,
            "sentiment": (round(float(sent), 4) if sent is not None else None),
            "bin": _bin_of(sent),
            "article_count": int(d.get("article_count") or 0),
            "price_at_record": d.get("price"),
            "consensus": cons.get("signal") or cons.get("consensus") or cons.get("action"),
            "consensus_score": cons.get("score") or cons.get("consensus_score"),
            "sector": d.get("sector"),
            "asset_class": d.get("asset_class"),
            "graded": False,
            "realized_return": None,
            "realized_horizon_days": None,
            "stale": None,
            "scored_at": None,
        })
        seen.add((run_date, tkr))
        added += 1
    # cap (keep newest)
    if len(rows) > MAX_LEDGER_ROWS:
        ledger["rows"] = rows[-MAX_LEDGER_ROWS:]
    return added


# ── step 2: grade ungraded rows against the scoring pipeline ────────
def grade_pending(ledger: Dict[str, Any], outcomes: List[Dict[str, Any]]) -> int:
    """Join ungraded ledger rows to scoring.json outcomes on (ticker, date).

    The scoring pipeline already computed entry/exit and return_pct, deduped and
    stale-flagged. We pick, per (ticker, predicted_at), the representative return
    (prefer a clean, equity outcome). That gives the realized forward move for the
    sentiment we recorded that day — no second price fetch, no new contamination.
    """
    # index: (ticker, predicted_date) -> chosen outcome
    idx: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for o in outcomes:
        tkr = o.get("ticker")
        pred = _date_of(o.get("predicted_at"))
        if not tkr or not pred:
            continue
        key = (tkr, pred)
        prev = idx.get(key)
        # prefer clean (non-stale) over stale; otherwise keep first
        if prev is None:
            idx[key] = o
        elif prev.get("stale_price_suspected") and not o.get("stale_price_suspected"):
            idx[key] = o

    graded = 0
    for r in ledger.get("rows", []):
        if r.get("graded"):
            continue
        o = idx.get((r.get("ticker"), r.get("date")))
        if not o or o.get("return_pct") is None:
            continue
        r["graded"] = True
        r["realized_return"] = round(float(o["return_pct"]), 4)
        r["stale"] = bool(o.get("stale_price_suspected"))
        r["scored_at"] = _date_of(o.get("scored_at"))
        lag = _days_between(r.get("date", ""), r.get("scored_at", ""))
        r["realized_horizon_days"] = lag
        graded += 1
    return graded


# ── step 3: build the calibration scorecard ─────────────────────────
def _horizon_bucket(days: Optional[int]) -> str:
    if days is None:
        return "unknown"
    if days <= 1:
        return "1d"
    if days <= 5:
        return "2-5d"
    return "6d+"


def build_calibration(ledger: Dict[str, Any]) -> Dict[str, Any]:
    rows = ledger.get("rows", [])
    graded = [r for r in rows if r.get("graded") and r.get("realized_return") is not None
              and r.get("sentiment") is not None]
    clean = [r for r in graded if not r.get("stale")]

    # by sentiment bin (clean only — stale returns are not trustworthy)
    by_bin: Dict[str, List[float]] = defaultdict(list)
    for r in clean:
        by_bin[r["bin"]].append(float(r["realized_return"]))
    bin_rows = []
    for name, _lo, _hi in BINS:
        st = _stats(by_bin.get(name, []))
        bin_rows.append({"bin": name, **st})

    # overhype vs legit, within strongly-positive sentiment
    strong_pos = [r for r in clean if float(r["sentiment"]) >= STRONG_POS]
    sp_n = len(strong_pos)
    sp_up = sum(1 for r in strong_pos if float(r["realized_return"]) > 0)
    overhype_rate = round(1 - (sp_up / sp_n), 4) if sp_n else None
    legit_rate = round(sp_up / sp_n, 4) if sp_n else None

    # strongly-negative: did the bad news actually precede a drop?
    strong_neg = [r for r in clean if float(r["sentiment"]) <= STRONG_NEG]
    sn_n = len(strong_neg)
    sn_down = sum(1 for r in strong_neg if float(r["realized_return"]) < 0)
    bad_news_confirmed = round(sn_down / sn_n, 4) if sn_n else None

    # realized horizon cuts
    by_h: Dict[str, List[float]] = defaultdict(list)
    for r in clean:
        by_h[_horizon_bucket(r.get("realized_horizon_days"))].append(float(r["realized_return"]))
    horizon_rows = [{"horizon": h, **_stats(by_h[h])} for h in ("1d", "2-5d", "6d+", "unknown") if by_h.get(h)]

    # overall correlation: does higher sentiment => higher return?
    corr = _pearson([(float(r["sentiment"]), float(r["realized_return"])) for r in clean])

    return {
        "graded_total": len(graded),
        "graded_clean": len(clean),
        "graded_stale": len(graded) - len(clean),
        "by_bin": bin_rows,
        "overhype": {
            "strong_pos_n": sp_n,
            "overhype_rate": overhype_rate,   # high sentiment, price FELL
            "legit_rate": legit_rate,         # high sentiment, price ROSE
            "strong_neg_n": sn_n,
            "bad_news_confirmed_rate": bad_news_confirmed,
        },
        "by_realized_horizon": horizon_rows,
        "sentiment_return_correlation": corr,
    }


# ── immediate (present-data) responsiveness ─────────────────────────
def responsiveness(signals: Dict[str, Any]) -> Dict[str, Any]:
    """How much is sentiment ALREADY moving consensus today? No grading needed —
    this is computed from the current signals.json and proves the wire is live."""
    pos_dir, neg_dir, hold_dir = [], [], []
    pairs: List[Tuple[float, float]] = []
    for d in signals.get("debates", []) or []:
        s = d.get("sentiment_score")
        if s is None:
            continue
        cons = (d.get("consensus") or {})
        sig = (cons.get("signal") or cons.get("consensus") or cons.get("action") or "").upper()
        cscore = cons.get("score") or cons.get("consensus_score")
        if cscore is not None:
            pairs.append((float(s), float(cscore)))
        if sig in _BUY:
            pos_dir.append(float(s))
        elif sig in _SELL:
            neg_dir.append(float(s))
        else:
            hold_dir.append(float(s))

    def _mean(xs):
        return round(sum(xs) / len(xs), 4) if xs else None

    return {
        "n_with_sentiment": len(pos_dir) + len(neg_dir) + len(hold_dir),
        "avg_sentiment_on_BUY_consensus": _mean(pos_dir),
        "avg_sentiment_on_SELL_consensus": _mean(neg_dir),
        "avg_sentiment_on_HOLD_ABSTAIN": _mean(hold_dir),
        "sentiment_vs_consensus_score_corr": _pearson(pairs),
    }


def deal_journal_news_proxy(out: Path) -> Dict[str, Any]:
    """Near-term realized proxy that already has outcomes attached today:
    the deal journal's news-backed-vs-silent and per-catalyst-class win rates."""
    dj = _load(Path(out) / "deal_journal.json", {})
    if not isinstance(dj, dict):
        return {}
    return {
        "news_vs_silence": dj.get("news_vs_silence"),
        "by_catalyst_class": dj.get("by_catalyst_class"),
        "linked_count": dj.get("linked_count"),
        "deals_count": dj.get("deals_count"),
    }


# ── notes ───────────────────────────────────────────────────────────
def _notes(cal: Dict[str, Any], resp: Dict[str, Any], added: int, graded: int,
           ledger_rows: int) -> List[str]:
    n: List[str] = []
    if cal["graded_clean"] == 0:
        n.append(
            "Calibration is ACCUMULATING. Sentiment was never persisted historically, "
            "so there is no backfill — grades begin from clean forward data. Expect ~10-20 "
            "trading days before bin verdicts leave 'thin'."
        )
    gc = cal["graded_clean"]
    corr = cal.get("sentiment_return_correlation")
    if gc >= MIN_N_BIN and corr is not None:
        if corr > 0.1:
            n.append(f"Sentiment shows POSITIVE predictive correlation with realized return (r={corr}) on {gc} clean graded names.")
        elif corr < -0.1:
            n.append(f"WARNING: sentiment is INVERSELY correlated with realized return (r={corr}) — the lexicon may be a contrarian signal, not a momentum one.")
        else:
            n.append(f"Sentiment is not yet predictive of realized return (r={corr}, {gc} clean).")
    oh = cal["overhype"]
    if oh["strong_pos_n"] >= MIN_N_BIN and oh["overhype_rate"] is not None:
        n.append(f"Of {oh['strong_pos_n']} strongly-positive-sentiment names, {oh['overhype_rate']*100:.0f}% FELL (overhype) vs {oh['legit_rate']*100:.0f}% rose (legit signal).")
    r = resp
    if r.get("avg_sentiment_on_BUY_consensus") is not None and r.get("avg_sentiment_on_HOLD_ABSTAIN") is not None:
        n.append(f"Live responsiveness: avg sentiment is {r['avg_sentiment_on_BUY_consensus']} on BUY consensus vs {r['avg_sentiment_on_HOLD_ABSTAIN']} on HOLD/ABSTAIN — the news→vote wire is active.")
    n.append(f"This cycle: recorded {added} ticker-day snapshots, graded {graded} prior rows. Ledger holds {ledger_rows} rows.")
    return n


# ── orchestrator ────────────────────────────────────────────────────
def build_sentiment_ledger(out_dir: Path) -> Dict[str, Any]:
    """Record today's sentiment, grade what can be graded, write the ledger and
    the calibration scorecard. Returns a small summary for the cycle log."""
    out = Path(out_dir)
    ledger_path = out / "sentiment_ledger.json"
    ledger = _load(ledger_path, {"version": LEDGER_VERSION, "rows": []})
    if not isinstance(ledger, dict) or "rows" not in ledger:
        ledger = {"version": LEDGER_VERSION, "rows": []}

    signals = _load(out / "signals.json", {})
    scoring = _load(out / "scoring.json", {})
    outcomes = scoring.get("outcomes", []) if isinstance(scoring, dict) else []

    added = record_cycle_snapshot(ledger, signals)
    graded = grade_pending(ledger, outcomes)
    ledger["version"] = LEDGER_VERSION
    ledger["generated_at"] = datetime.now(timezone.utc).isoformat()
    _dump(ledger_path, ledger)

    cal = build_calibration(ledger)
    resp = responsiveness(signals)
    proxy = deal_journal_news_proxy(out)
    notes = _notes(cal, resp, added, graded, len(ledger.get("rows", [])))

    calibration = {
        "version": LEDGER_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ledger_rows": len(ledger.get("rows", [])),
        "recorded_this_cycle": added,
        "graded_this_cycle": graded,
        "calibration": cal,
        "responsiveness_now": resp,
        "deal_journal_proxy": proxy,
        "notes": notes,
    }
    _dump(out / "sentiment_calibration.json", calibration)
    return {
        "ledger_rows": len(ledger.get("rows", [])),
        "recorded": added,
        "graded": graded,
        "graded_clean_total": cal["graded_clean"],
        "corr": cal.get("sentiment_return_correlation"),
    }


if __name__ == "__main__":  # pragma: no cover
    import sys
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")
    print(json.dumps(build_sentiment_ledger(base), indent=2))
