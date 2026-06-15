"""
silmaril.analytics.source_fingerprint — judge the messengers (Alpha 0.007).

"We need to discern between what signals are adding noise and what signals are
giving us potential truth." Encoded: every news SOURCE now gets the same
treatment every stock and every agent gets — a permanent record, a graded
fingerprint, and a verdict with confidence intervals.

THE LOOP (self-contained on docs/data, runs every cycle):
  RECORD   every headline this cycle -> {source, ticker, ET date, word-score,
           price} appended to source_history.json (overflow archived forever).
  GRADE    join each row to the ticker's NEXT recorded price (news_history) ->
           directional outcome: did this source's tilt point the right way?
  JUDGE    per source: n, hit-rate with Wilson 95% CI, avg directional return.
           Verdicts: PROVEN-SIGNAL (CI floor > 50%, n>=30) · FADE-WORTHY
           (CI ceiling < 45%, n>=30 — reliably wrong is also information) ·
           UNPROVEN (everything else, with n shown).
  WEIGHT   verdicts become live multipliers the word engine applies per
           headline as it scores (PROVEN 1.2x · FADE 0.8x · UNPROVEN 1.0x,
           hard-clamped) — sources earn or lose their voice with evidence.
  JUDGE THE JUDGE  the rankings file carries its own calibration row: the
           weighted composite's hit-rate vs the unweighted one, so the
           weighting scheme itself is on trial, same as everything here.

Deterministic, stdlib + our own word engine, offline-safe, additive.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MIN_TILT = 0.25          # a headline must lean to count as a directional call
MIN_N_VERDICT = 30       # rows needed before PROVEN/FADE verdicts unlock
CAP_PER_SOURCE = 4000    # runtime rows per source; overflow -> archive
W_PROVEN, W_FADE, W_DEFAULT = 1.2, 0.8, 1.0


def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _wilson(w: int, n: int, z: float = 1.96) -> Tuple[float, float, float]:
    if n <= 0:
        return 0.0, 0.0, 1.0
    p = w / n
    den = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / den
    rad = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / den
    return p, max(0.0, ctr - rad), min(1.0, ctr + rad)


def _et_date(now: Optional[datetime] = None) -> str:
    now = now or datetime.now(timezone.utc)
    return (now + timedelta(hours=-4)).strftime("%Y-%m-%d")


def record_sources(out: Path) -> int:
    """Append this cycle's headlines to each source's permanent record."""
    signals = _load(out / "signals.json", {})
    hist: Dict[str, List[dict]] = _load(out / "source_history.json", {})
    if not isinstance(hist, dict):
        hist = {}
    try:
        from .sentiment import score_text
    except Exception:
        return 0
    date = _et_date()
    added = 0
    for d in signals.get("debates") or []:
        tkr = str(d.get("ticker") or "")
        try:
            px = float(d.get("price") or 0)
        except Exception:
            px = 0.0
        if not tkr or px <= 0:
            continue
        for h in d.get("recent_headlines") or []:
            src = str((h or {}).get("source") or "").strip()
            title = str((h or {}).get("title") or "").strip()
            if not src or not title:
                continue
            try:
                from .sentiment import headline_relevance
                if headline_relevance(title, tkr) <= 0.0:
                    continue  # same-name collision — not this stock's news
            except Exception:
                pass
            rows = hist.setdefault(src, [])
            key = (date, tkr, title[:60])
            if any((r.get("date"), r.get("ticker"),
                    str(r.get("t") or "")[:60]) == key for r in rows[-200:]):
                continue
            rows.append({"date": date, "ticker": tkr,
                         "sent": round(float(score_text(title)), 3),
                         "price": px, "t": title[:120]})
            added += 1
    # lossless caps
    try:
        from .archive import archive_then_trim
        for src in list(hist):
            hist[src] = archive_then_trim(out, "source_history",
                                          hist[src], CAP_PER_SOURCE)
    except Exception:
        for src in list(hist):
            hist[src] = hist[src][-CAP_PER_SOURCE:]
    (out / "source_history.json").write_text(json.dumps(hist))
    return added


def build_source_rankings(out_dir: str) -> Dict[str, Any]:
    out = Path(out_dir)
    record_sources(out)
    hist: Dict[str, List[dict]] = _load(out / "source_history.json", {})
    nh = _load(out / "news_history.json", {})

    # (ticker, date) -> sorted price timeline for forward joins
    timelines: Dict[str, List[Tuple[str, float]]] = {}
    for tkr, rows in (nh or {}).items():
        tl = sorted(((r.get("date"), float(r.get("price") or 0))
                     for r in rows or [] if r.get("date") and r.get("price")),
                    key=lambda x: x[0])
        if tl:
            timelines[tkr] = tl

    def fwd_ret(tkr: str, date: str, px: float) -> Optional[float]:
        for d2, p2 in timelines.get(tkr, []):
            if d2 > date and p2 > 0 and px > 0:
                return p2 / px - 1.0
        return None

    boards: List[Dict[str, Any]] = []
    w_hits = w_n = u_hits = u_n = 0
    for src, rows in hist.items():
        n = hits = 0
        sum_dir = 0.0
        for r in rows:
            s = float(r.get("sent") or 0)
            if abs(s) < MIN_TILT:
                continue
            fr = fwd_ret(str(r.get("ticker")), str(r.get("date")),
                         float(r.get("price") or 0))
            if fr is None:
                continue
            d = (1 if s > 0 else -1) * fr
            n += 1
            hits += 1 if d > 0 else 0
            sum_dir += d
        if n == 0:
            boards.append({"source": src, "n": 0, "rows": len(rows),
                           "verdict": "UNPROVEN (no graded calls yet)",
                           "weight": W_DEFAULT})
            continue
        p, lo, hi = _wilson(hits, n)
        if n >= MIN_N_VERDICT and lo > 0.50:
            verdict, weight = "PROVEN-SIGNAL", W_PROVEN
        elif n >= MIN_N_VERDICT and hi < 0.45:
            verdict, weight = "FADE-WORTHY (reliably wrong)", W_FADE
        else:
            verdict, weight = f"UNPROVEN (n={n})", W_DEFAULT
        boards.append({"source": src, "n": n, "rows": len(rows),
                       "hit_rate": round(p, 3),
                       "ci": [round(lo, 3), round(hi, 3)],
                       "avg_dir_ret_pct": round(100 * sum_dir / n, 3),
                       "verdict": verdict, "weight": weight})
        # judge-the-judge inputs: weighted vs unweighted composite
        u_n += n
        u_hits += hits
        w_n += int(round(n * weight))
        w_hits += int(round(hits * weight))

    graded = [b for b in boards if b.get("n", 0) > 0]
    graded.sort(key=lambda b: (b.get("hit_rate") or 0, b["n"]), reverse=True)
    meta = {
        "unweighted_hit": round(u_hits / u_n, 3) if u_n else None,
        "weighted_hit": round(w_hits / w_n, 3) if w_n else None,
        "note": ("judge-the-judge: if weighted_hit doesn't beat unweighted as "
                 "verdicts unlock, the weighting scheme itself gets demoted"),
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources_tracked": len(hist),
        "sources_graded": len(graded),
        "board_top": graded[:12],
        "board_bottom": list(reversed(graded[-8:])) if len(graded) > 8 else [],
        "all": sorted(boards, key=lambda b: -(b.get("n") or 0)),
        "weighting": {"proven": W_PROVEN, "fade": W_FADE,
                      "default": W_DEFAULT, "min_n": MIN_N_VERDICT},
        "calibration": meta,
    }
    (out / "source_rankings.json").write_text(json.dumps(payload, indent=2))
    return {"tracked": len(hist), "graded": len(graded),
            "top": (graded[0]["source"] if graded else None),
            "weighted_vs_unweighted": (meta["weighted_hit"],
                                       meta["unweighted_hit"])}
