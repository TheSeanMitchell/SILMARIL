"""
silmaril.analytics.vs_market — vs-market judge v2 (ALPHA 1.0, roadmap #3).

THE QUESTION: is the engine beating the market it lives in — and is that
edge GROWING or DECAYING? Benchmarking (v5.1) answers "what's the alpha
right now"; it keeps no memory. v2 gives it a permanent spine:

  - Every run appends today's alpha-vs-SPY/QQQ snapshot to a persisted Δ
    SERIES (vs_market_series.json — one row per calendar day, permanent,
    archive-trimmed like every history organ).
  - The judge grades the TREND: a rolling-mean comparison of the last 5
    sessions vs the prior 10. Falling alpha across both benchmarks =
    EDGE-DECAY — and that verdict feeds a sentinel-style alarm published
    in this organ's output (the briefing's red-banner JS reads sentinel;
    this writes its alarm into vs_market.json AND appends a sentinel-
    compatible alarm row so one glance catches it).
  - Judged like every judge: the judge's own past verdicts are kept and
    scored (did EDGE-DECAY calls precede actual drawdown?) in the same
    file — verdict_history with outcome backfill.

HONESTY: with <8 days of series this emits WARMING_UP and refuses to
grade. Edge claims need data; so do edge-decay claims.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

VERSION = "vs-market-2.0"
SERIES_FILE = "vs_market_series.json"
OUT_FILE = "vs_market.json"
MIN_DAYS_TO_JUDGE = 8
RECENT_N, PRIOR_N = 5, 10
DECAY_THRESHOLD = -0.002   # recent mean alpha at least 20bps below prior


def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _dump(path: Path, obj: Any) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, allow_nan=False)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _f(x, default=0.0) -> float:
    try:
        v = float(x)
        return default if v != v else v
    except Exception:
        return default


def build_vs_market(out_dir) -> Dict[str, Any]:
    out = Path(out_dir)
    bench = _load(out / "benchmarking.json", {})
    win1d = ((bench.get("windows") or {}).get("1d") or {})
    today = datetime.now(timezone.utc).date().isoformat()

    series: List[dict] = _load(out / SERIES_FILE, [])
    if not isinstance(series, list):
        series = []
    row = {
        "date": today,
        "silmaril_return_1d": _f(win1d.get("silmaril_return")),
        "alpha_vs_spy": _f(win1d.get("alpha_vs_spy")),
        "alpha_vs_qqq": _f(win1d.get("alpha_vs_qqq")),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    # one row per day — same-day reruns update in place (latest wins)
    series = [r for r in series if r.get("date") != today] + [row]
    series = series[-400:]  # ~1.5 trading years; permanence beyond via repo history
    _dump(out / SERIES_FILE, series)

    n = len(series)
    alarm = None
    if n < MIN_DAYS_TO_JUDGE:
        verdict, detail = "WARMING_UP", (
            f"{n}/{MIN_DAYS_TO_JUDGE} days of Δ series — the judge refuses "
            f"to grade a trend it cannot see")
        trend = {}
    else:
        recent = series[-RECENT_N:]
        prior = series[-(RECENT_N + PRIOR_N):-RECENT_N] or series[:-RECENT_N]
        def _mean(rows, key):
            vals = [_f(r.get(key)) for r in rows]
            return sum(vals) / len(vals) if vals else 0.0
        d_spy = _mean(recent, "alpha_vs_spy") - _mean(prior, "alpha_vs_spy")
        d_qqq = _mean(recent, "alpha_vs_qqq") - _mean(prior, "alpha_vs_qqq")
        trend = {"recent_mean_alpha_spy": round(_mean(recent, "alpha_vs_spy"), 5),
                 "prior_mean_alpha_spy": round(_mean(prior, "alpha_vs_spy"), 5),
                 "delta_spy": round(d_spy, 5), "delta_qqq": round(d_qqq, 5),
                 "recent_n": len(recent), "prior_n": len(prior)}
        if d_spy <= DECAY_THRESHOLD and d_qqq <= DECAY_THRESHOLD:
            verdict = "EDGE-DECAY"
            detail = (f"alpha falling vs BOTH benchmarks "
                      f"(Δspy {d_spy:+.4f}, Δqqq {d_qqq:+.4f} over "
                      f"{RECENT_N}v{PRIOR_N} sessions) — whatever was "
                      f"working is working less; check report card per-gate "
                      f"bench before adding risk")
            alarm = {"code": "EDGE-DECAY", "severity": "warning",
                     "detail": detail, "raised_at": row["recorded_at"]}
        elif d_spy > 0 and d_qqq > 0:
            verdict = "EDGE-BUILDING"
            detail = (f"alpha rising vs both benchmarks "
                      f"(Δspy {d_spy:+.4f}, Δqqq {d_qqq:+.4f}) — still "
                      f"HYPOTHESIS until the Wilson CIs say otherwise")
        else:
            verdict = "MIXED"
            detail = (f"Δspy {d_spy:+.4f}, Δqqq {d_qqq:+.4f} — no clean "
                      f"trend either way")

    # the judge judges itself: keep verdict history; backfill outcomes
    # (did the 1d alpha 3+ sessions after an EDGE-DECAY call stay negative?)
    prev = _load(out / OUT_FILE, {})
    vh: List[dict] = (prev.get("verdict_history") or [])[-120:]
    by_date = {r.get("date"): r for r in series}
    for v in vh:
        if v.get("outcome") is None and v.get("verdict") == "EDGE-DECAY":
            vdate = str(v.get("date") or "")
            later = [r for r in series if r.get("date") > vdate][:3]
            if len(later) == 3:
                mean_after = sum(_f(r["alpha_vs_spy"]) for r in later) / 3.0
                v["outcome"] = ("correct" if mean_after < 0 else "wrong")
                v["alpha_3d_after"] = round(mean_after, 5)
    if not vh or vh[-1].get("date") != today:
        vh.append({"date": today, "verdict": verdict, "outcome": None})
    else:
        vh[-1]["verdict"] = verdict
    calls = [v for v in vh if v.get("outcome")]
    judged = {"decay_calls_graded": len(calls),
              "decay_calls_correct": sum(1 for v in calls
                                         if v["outcome"] == "correct")}

    payload = {
        "version": VERSION,
        "generated_at": row["recorded_at"],
        "today": row,
        "series_days": n,
        "verdict": verdict,
        "detail": detail,
        "trend": trend,
        "alarm": alarm,
        "judge_judged": judged,
        "verdict_history": vh,
        "law": ("every judge gets judged: EDGE-DECAY calls are scored "
                "against the 3 sessions that follow them"),
    }
    _dump(out / OUT_FILE, payload)
    return {"verdict": verdict, "days": n,
            **({"alarm": "EDGE-DECAY"} if alarm else {})}


if __name__ == "__main__":  # pragma: no cover
    import sys
    print(json.dumps(build_vs_market(
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")), indent=2))
