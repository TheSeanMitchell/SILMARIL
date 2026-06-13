"""
DR. STRANGE — the shadow oracle (Week-2 roadmap item, no live orders, ever).

"I went forward in time to view alternate futures." This module does exactly
that, with arithmetic instead of magic: for every stock, it builds an EMPIRICAL
distribution of what actually happened the day AFTER each kind of word-day this
system has recorded (strong-positive words, positive, quiet, negative,
strong-negative — from news_history's sent/cat/antic columns). Then, for
today's word-state, it samples 1,000 three-day futures from that stock's own
observed history and only opens its mouth when >=90% of the futures agree on a
direction. One pick per day, maximum. Every pick is logged and graded against
what really happened next — Dr. Strange keeps his own career record and earns
trust the same way every agent here does: realized outcomes.

Deterministic (seeded by date+ticker), stdlib-only, explainable end to end:
no LLMs, no synthetic data — only this system's own recorded history.
Today, with 1-2 rows per ticker, it will honestly say "still building
history"; every clean trading day makes the futures sharper. SPCX's debut
rows land in the same store the moment it lists.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

PATHS = 1000          # Monte-Carlo futures per ticker
HORIZON = 3           # days forward per future
AGREEMENT = 0.90      # fraction of paths that must share a sign
MIN_OBS = 5           # min observed day-pairs in the matched regime
MIN_OBS_ALL = 8       # fallback: min day-pairs across all regimes
MIN_EDGE = 0.002      # median terminal move must exceed 20 bps
MAX_HISTORY = 200     # picks kept in the career log


# ── regime classification (same word thresholds the desk trades on) ─────────
def _regime(row: Dict[str, Any]) -> str:
    sent = float(row.get("sent") or 0.0)
    cat = row.get("cat")
    antic = float(row.get("antic") or 0.0)
    c = float(cat) if cat is not None else 0.0
    if c >= 0.5 or sent >= 0.45 or antic >= 0.5:
        return "strong_pos"
    if c <= -0.5 or sent <= -0.45 or antic <= -0.5:
        return "strong_neg"
    if sent >= 0.2 or antic >= 0.25:
        return "pos"
    if sent <= -0.2 or antic <= -0.25:
        return "neg"
    return "quiet"


def _day_pairs(rows: List[Dict[str, Any]]) -> List[Tuple[str, float]]:
    """(regime_of_day_i, next_day_return) for consecutive recorded days."""
    out: List[Tuple[str, float]] = []
    rs = sorted((r for r in rows if r.get("date")), key=lambda r: r["date"])
    for a, b in zip(rs, rs[1:]):
        try:
            p0, p1 = float(a.get("price") or 0), float(b.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if p0 > 0 and p1 > 0:
            out.append((_regime(a), p1 / p0 - 1.0))
    return out


def _simulate(sample: List[float], seed: str) -> Tuple[float, float, float, float]:
    """1000 seeded 3-day futures from the empirical sample.
    Returns (agreement_signed, med, p10, p90); agreement_signed>0 = up."""
    rng = random.Random(seed)
    terms: List[float] = []
    for _ in range(PATHS):
        v = 1.0
        for _ in range(HORIZON):
            v *= 1.0 + rng.choice(sample)
        terms.append(v - 1.0)
    terms.sort()
    pos = sum(1 for t in terms if t > 0) / PATHS
    agree = pos if pos >= 0.5 else -(1.0 - pos)
    return agree, median(terms), terms[int(PATHS * 0.10)], terms[int(PATHS * 0.90)]


def build_dr_strange(out_dir: str) -> Dict[str, Any]:
    out = Path(out_dir)
    try:
        nh = json.loads((out / "news_history.json").read_text())
    except Exception:
        nh = {}

    try:
        tfp = (json.loads((out / "timing_fingerprint.json").read_text())
               or {}).get("fingerprints") or {}
    except Exception:
        tfp = {}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = out / "dr_strange.json"
    try:
        prev = json.loads(path.read_text())
    except Exception:
        prev = {}
    picks: List[Dict[str, Any]] = list(prev.get("picks") or [])

    # ── grade unresolved past picks against what really happened ───────────
    for p in picks:
        if p.get("realized") is not None:
            continue
        rows = sorted((r for r in (nh.get(p["ticker"]) or [])
                       if r.get("date") and r.get("price")),
                      key=lambda r: r["date"])
        later = [r for r in rows if r["date"] > p["date"]]
        if later and float(p.get("price") or 0) > 0:
            realized = float(later[-1]["price"]) / float(p["price"]) - 1.0
            p["realized"] = round(realized, 5)
            p["realized_through"] = later[-1]["date"]
            p["hit"] = (realized > 0) == (p["direction"] == "UP")

    evaluated = 0
    thin = 0
    qualified: List[Dict[str, Any]] = []
    for tkr, rows in nh.items():
        pairs = _day_pairs(rows or [])
        if not pairs or not rows:
            thin += 1
            continue
        last = sorted((r for r in rows if r.get("date")),
                      key=lambda r: r["date"])[-1]
        reg = _regime(last)
        sample = [r for g, r in pairs if g == reg]
        basis = f"{len(sample)}d in '{reg}'"
        if len(sample) < MIN_OBS:
            allr = [r for _, r in pairs]
            if len(allr) >= MIN_OBS_ALL:
                sample, basis = allr, f"{len(allr)}d all-regime (thin '{reg}')"
            else:
                thin += 1
                continue
        evaluated += 1
        agree, med, p10, p90 = _simulate(sample, f"{today}:{tkr}")
        if abs(agree) >= AGREEMENT and abs(med) >= MIN_EDGE:
            qualified.append({
                "ticker": tkr, "direction": "UP" if agree > 0 else "DOWN",
                "agreement": round(abs(agree), 3), "median": round(med, 5),
                "p10": round(p10, 5), "p90": round(p90, 5),
                "regime": reg, "basis": basis,
                "price": last.get("price"), "date": last.get("date"),
                # the PLAN: his clock — buy his low window, sell his high
                **(lambda f: ({"buy_window": f.get("best_buy_window"),
                               "sell_window": f.get("best_sell_window"),
                               "pred_low": f.get("floor"),
                               "pred_high": f.get("ceiling")}
                              if f and not f.get("learning", True) else {}))(
                    tfp.get(tkr) or {}),
            })

    qualified.sort(key=lambda q: (q["agreement"], abs(q["median"])), reverse=True)
    pick: Optional[Dict[str, Any]] = None
    if qualified and not any(p.get("date") == today for p in picks):
        pick = dict(qualified[0])
        pick["date"] = today
        picks.append(pick)
        try:
            from .archive import archive_then_trim as _att
            picks = _att(out, "dr_strange_picks", picks, MAX_HISTORY)
        except Exception:
            picks = picks[-MAX_HISTORY:]

    resolved = [p for p in picks if p.get("realized") is not None]
    hits = sum(1 for p in resolved if p.get("hit"))
    career = {
        "picks": len(picks), "resolved": len(resolved), "hits": hits,
        "hit_rate": round(hits / len(resolved), 3) if resolved else None,
        "avg_move": (round(sum(p["realized"] for p in resolved) / len(resolved), 5)
                     if resolved else None),
    }

    note = (f"{evaluated} names had enough recorded history to simulate; "
            f"{thin} still building history. "
            + (f"{len(qualified)} future(s) cleared the {int(AGREEMENT*100)}% bar."
               if qualified else
               f"No name cleared the {int(AGREEMENT*100)}% bar — the oracle "
               f"stays silent rather than guess."))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": today, "evaluated": evaluated, "thin": thin,
        "params": {"paths": PATHS, "horizon_days": HORIZON,
                   "agreement": AGREEMENT, "min_obs": MIN_OBS},
        "qualified": qualified[:5], "pick": pick or (picks[-1] if picks and picks[-1].get("date") == today else None),
        "career": career, "picks": picks, "note": note, "shadow_only": True,
    }
    path.write_text(json.dumps(payload, indent=2))
    return {"evaluated": evaluated, "qualified": len(qualified),
            "pick": (pick or {}).get("ticker"), "career": career["hit_rate"]}
