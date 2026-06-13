"""
silmaril.learning.agent_scorecard — A brutally honest report card per agent.

Win-rate lies. An agent can be "right" 80% of the time and still lose money
(ATLAS: 80.0% win, -$28.68 realized) because the losses are bigger than the
wins, or because the wins are HOLDs on flat names. This module grades every
agent on what actually matters — realized, signed, CLEAN return — and slices it
by day, week, and month so drift and improvement are both visible.

Source of truth: scoring.json `outcomes` (the same deduped, stale-flagged record
that drives the learning loop). For each outcome we compute the signed realized
return the way edge_study does: BUY -> +move, SELL -> -move, HOLD/ABSTAIN ->
no directional P&L. Stale-priced outcomes are reported but EXCLUDED from grades.

The grade is deliberately unflattering:
    REAL EDGE        clean signed return > 0 with t > 2 over >= MIN_CLEAN samples
    EDGE (SOFT)      positive, t in (1.5, 2]
    WIN-RATE MIRAGE  win_rate >= 0.60 but clean signed return <= 0  (the trap)
    NO EDGE          |t| <= 1.5
    NEGATIVE EDGE    clean signed return < 0 with t < -1.5
    INSUFFICIENT     fewer than MIN_CLEAN clean directional samples (noise)

Read-only. Writes docs/data/agent_scorecard.json. Safe every cycle.
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

SCORECARD_VERSION = "agent-scorecard-1.0"
MIN_CLEAN = 30                 # below this, no edge claim — it's noise
DAILY_WINDOW = 30              # how many recent days to expose day-by-day
RECENT_CALLS = 12             # most-recent graded calls shown per agent

_BUY = {"BUY", "STRONG_BUY"}
_SELL = {"SELL", "STRONG_SELL"}
_DIRECTIONAL = _BUY | _SELL

# Instrument classification (mirrors edge_study) so "edge" can be checked for the
# beta trap: an all-BUY agent in a one-regime rising tape is market beta, not skill,
# and crypto/macro calls dilute the equity mission.
_FOREX = {"UUP", "FXE", "FXY", "FXF", "FXB", "FXC", "FXA", "CYB", "UDN", "USDU"}
_COMMODITY = {"GLD", "SLV", "IAU", "GDX", "GDXJ", "USO", "UNG", "DBC", "PDBC", "DBA", "CPER"}
_BROAD_ETF = {"SPY", "VOO", "VTI", "QQQ", "DIA", "IWM", "EFA", "EEM", "IVV"}


def _instrument_kind(ticker: Optional[str]) -> str:
    t = (ticker or "").upper()
    if not t:
        return "equity"
    if t.endswith("-USD") or t.endswith("-USDT") or t.endswith("USDT") or "-USD" in t:
        return "crypto"
    if t in _FOREX or t in _COMMODITY:
        return "macro"
    if t in _BROAD_ETF:
        return "broad_etf"
    return "equity"


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


def _date_of(iso: Optional[str]) -> str:
    return str(iso)[:10] if iso else ""


def _iso_week(d: str) -> str:
    try:
        dt = datetime.fromisoformat(d[:10])
        y, w, _ = dt.isocalendar()
        return f"{y}-W{w:02d}"
    except Exception:
        return ""


def _signed_return(o: Dict[str, Any]) -> Optional[float]:
    sig = o.get("signal")
    r = o.get("return_pct")
    if r is None:
        return None
    r = float(r)
    if sig in _BUY:
        return r
    if sig in _SELL:
        return -r
    return None


def _stats(xs: List[float]) -> Dict[str, Any]:
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": 0.0, "hit_rate": 0.0, "t_stat": 0.0, "sum": 0.0}
    mean = sum(xs) / n
    sd = (sum((x - mean) ** 2 for x in xs) / n) ** 0.5 if n > 1 else 0.0
    t = (mean / (sd / math.sqrt(n))) if sd > 0 else 0.0
    hit = sum(1 for x in xs if x > 0) / n
    return {"n": n, "mean": round(mean, 4), "hit_rate": round(hit, 4),
            "t_stat": round(t, 3), "sum": round(sum(xs), 4)}


def _grade(clean_signed: List[float], win_rate_clean: float) -> Dict[str, Any]:
    n = len(clean_signed)
    if n < MIN_CLEAN:
        return {"grade": "I", "verdict": "INSUFFICIENT",
                "why": f"only {n} clean directional samples (< {MIN_CLEAN}); any win-rate here is noise."}
    s = _stats(clean_signed)
    mean, t = s["mean"], s["t_stat"]
    if win_rate_clean >= 0.60 and mean <= 0:
        return {"grade": "D", "verdict": "WIN-RATE MIRAGE",
                "why": f"wins {win_rate_clean*100:.0f}% but mean signed return {mean:+.3f}% — right often, profitable never."}
    if mean > 0 and t > 2.0:
        return {"grade": "A", "verdict": "REAL EDGE",
                "why": f"mean {mean:+.3f}% (t={t:+.2f}) over {n} clean — unlikely to be luck."}
    if mean > 0 and t > 1.5:
        return {"grade": "B", "verdict": "EDGE (SOFT)",
                "why": f"mean {mean:+.3f}% (t={t:+.2f}) — promising but not yet significant."}
    if mean < 0 and t < -1.5:
        return {"grade": "F", "verdict": "NEGATIVE EDGE",
                "why": f"mean {mean:+.3f}% (t={t:+.2f}) — actively loses on clean data."}
    return {"grade": "C", "verdict": "NO EDGE",
            "why": f"mean {mean:+.3f}% (t={t:+.2f}) — indistinguishable from a coin flip."}


def _time_buckets(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """items: list of {date, signed, win} for CLEAN directional outcomes."""
    by_day: Dict[str, List[Dict]] = defaultdict(list)
    by_week: Dict[str, List[Dict]] = defaultdict(list)
    by_month: Dict[str, List[Dict]] = defaultdict(list)
    for it in items:
        d = it["date"]
        if not d:
            continue
        by_day[d].append(it)
        by_week[_iso_week(d)].append(it)
        by_month[d[:7]].append(it)

    def roll(group: Dict[str, List[Dict]], limit: Optional[int] = None) -> List[Dict[str, Any]]:
        keys = sorted(group.keys())
        if limit:
            keys = keys[-limit:]
        rows = []
        for k in keys:
            xs = [g["signed"] for g in group[k]]
            st = _stats(xs)
            rows.append({"period": k, "n": st["n"], "win_rate": st["hit_rate"],
                         "mean_return": st["mean"], "sum_return": st["sum"]})
        return rows

    return {
        "daily": roll(by_day, DAILY_WINDOW),
        "weekly": roll(by_week),
        "monthly": roll(by_month),
    }


def build_agent_scorecard(out_dir: Path) -> Dict[str, Any]:
    out = Path(out_dir)
    scoring = _load(out / "scoring.json", {})
    outcomes = scoring.get("outcomes", []) if isinstance(scoring, dict) else []

    by_agent: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for o in outcomes:
        a = o.get("agent")
        if a:
            by_agent[a].append(o)

    cards: List[Dict[str, Any]] = []
    for agent, outs in by_agent.items():
        clean = [o for o in outs if not o.get("stale_price_suspected")]
        stale_n = len(outs) - len(clean)

        # action mix (includes HOLD/ABSTAIN — that's the yes/no/abstain picture)
        action_mix: Dict[str, int] = defaultdict(int)
        for o in outs:
            action_mix[(o.get("signal") or "?").upper()] += 1

        # clean directional, signed
        clean_dir_items: List[Dict[str, Any]] = []
        for o in clean:
            sr = _signed_return(o)
            if sr is None:  # HOLD/ABSTAIN — no directional P&L
                continue
            clean_dir_items.append({
                "date": _date_of(o.get("scored_at")) or _date_of(o.get("predicted_at")),
                "signed": sr,
                "win": bool(o.get("correct")),
            })
        clean_signed = [it["signed"] for it in clean_dir_items]
        win_rate_clean = (sum(1 for it in clean_dir_items if it["signed"] > 0) / len(clean_dir_items)) \
            if clean_dir_items else 0.0

        overall = _stats(clean_signed)
        grade = _grade(clean_signed, win_rate_clean)
        buckets = _time_buckets(clean_dir_items)

        # recent graded calls (clean, any signal) for the "today's choices" view
        graded_sorted = sorted(
            [o for o in clean if o.get("return_pct") is not None],
            key=lambda o: o.get("scored_at") or "", reverse=True,
        )[:RECENT_CALLS]
        recent = [{
            "date": _date_of(o.get("scored_at")),
            "ticker": o.get("ticker"),
            "signal": o.get("signal"),
            "conviction": round(float(o.get("conviction") or 0), 3),
            "return_pct": round(float(o.get("return_pct") or 0), 3),
            "signed_return": (round(_signed_return(o), 3) if _signed_return(o) is not None else None),
            "correct": bool(o.get("correct")),
        } for o in graded_sorted]

        # honest caveats — a grade alone hides the beta trap
        dir_signals = [(o.get("signal") or "").upper() for o in clean if _signed_return(o) is not None]
        n_buy = sum(1 for s in dir_signals if s in _BUY)
        n_sell = sum(1 for s in dir_signals if s in _SELL)
        n_dir = max(1, n_buy + n_sell)
        direction_concentration = round(max(n_buy, n_sell) / n_dir, 3)
        inst_counts: Dict[str, int] = defaultdict(int)
        for o in clean:
            if _signed_return(o) is not None:
                inst_counts[_instrument_kind(o.get("ticker"))] += 1
        non_equity = sum(v for k, v in inst_counts.items() if k not in ("equity",))
        non_equity_frac = round(non_equity / n_dir, 3)

        caveats: List[str] = []
        if grade["grade"] in ("A", "B"):
            if direction_concentration >= 0.9 and n_dir >= MIN_CLEAN:
                side = "BUY" if n_buy >= n_sell else "SELL"
                caveats.append(
                    f"BETA TRAP: {direction_concentration*100:.0f}% of clean calls are {side}, and the only "
                    "observed regime so far is RISK_ON. An all-one-side agent in a rising tape is hard to "
                    "distinguish from simply being long the market — this edge is untested when the tape turns."
                )
            if non_equity_frac >= 0.4:
                caveats.append(
                    f"{non_equity_frac*100:.0f}% of clean directional calls are non-equity "
                    f"({dict(inst_counts)}); the equity-mission edge may be weaker than the headline grade."
                )
        if grade["grade"] != "I" and (len(clean) / max(1, len(outs))) < 0.5:
            caveats.append(
                f"Over half this agent's outcomes ({stale_n}/{len(outs)}) are stale-priced and excluded; "
                "the graded sample is a minority of its activity."
            )

        cards.append({
            "agent": agent,
            "grade": grade["grade"],
            "verdict": grade["verdict"],
            "why": grade["why"],
            "caveats": caveats,
            "samples": {
                "total": len(outs),
                "clean": len(clean),
                "stale": stale_n,
                "clean_pct": round(len(clean) / len(outs), 3) if outs else 0.0,
                "clean_directional": len(clean_signed),
            },
            "clean_performance": {
                "win_rate": round(win_rate_clean, 4),
                "mean_signed_return": overall["mean"],
                "sum_signed_return": overall["sum"],
                "t_stat": overall["t_stat"],
            },
            "direction_concentration": direction_concentration,
            "instrument_mix": dict(inst_counts),
            "action_mix": dict(action_mix),
            "by_period": buckets,
            "recent_calls": recent,
        })

    # rank: edge first (A>B>C>D>F>I), then by clean sum return
    order = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 4, "I": 5}
    cards.sort(key=lambda c: (order.get(c["grade"], 9),
                              -(c["clean_performance"]["sum_signed_return"] or 0)))

    # honest system-level notes
    notes: List[str] = []
    real = [c["agent"] for c in cards if c["grade"] in ("A", "B")]
    mirage = [c["agent"] for c in cards if c["verdict"] == "WIN-RATE MIRAGE"]
    insufficient = [c["agent"] for c in cards if c["verdict"] == "INSUFFICIENT"]
    negative = [c["agent"] for c in cards if c["verdict"] == "NEGATIVE EDGE"]
    if real:
        notes.append("Agents with a real/soft clean edge: " + ", ".join(real) + ".")
    else:
        notes.append("No agent yet shows a statistically significant clean edge — expected this early; "
                     "keep accumulating clean forward data.")
    beta = [c["agent"] for c in cards if any("BETA TRAP" in cv for cv in c.get("caveats", []))]
    if beta:
        notes.append("READ THE CAVEAT before trusting these grades — possible market beta, not skill "
                     "(all-one-side in a single RISK_ON regime): " + ", ".join(beta)
                     + ". The grade holds only if the edge survives a risk-off tape.")
    if mirage:
        notes.append("WIN-RATE MIRAGE (right often, not profitable): " + ", ".join(mirage) + ". Win-rate is misleading these.")
    if negative:
        notes.append("Negative clean edge (actively losing): " + ", ".join(negative) + ".")
    if insufficient:
        notes.append(f"{len(insufficient)} agents lack {MIN_CLEAN}+ clean directional samples; their numbers are noise: "
                     + ", ".join(insufficient[:10]) + ("…" if len(insufficient) > 10 else "") + ".")

    total_clean = sum(c["samples"]["clean"] for c in cards)
    total_all = sum(c["samples"]["total"] for c in cards)
    payload = {
        "version": SCORECARD_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agents_graded": len(cards),
        "outcomes_total": total_all,
        "outcomes_clean": total_clean,
        "stale_pct": round(1 - total_clean / total_all, 3) if total_all else 0.0,
        "min_clean_for_grade": MIN_CLEAN,
        "grade_counts": {g: sum(1 for c in cards if c["grade"] == g) for g in ("A", "B", "C", "D", "F", "I")},
        "cards": cards,
        "notes": notes,
    }
    _dump(out / "agent_scorecard.json", payload)
    return {
        "agents": len(cards),
        "real_edge": real,
        "mirage": mirage,
        "stale_pct": payload["stale_pct"],
    }


if __name__ == "__main__":  # pragma: no cover
    import sys
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs/data")
    print(json.dumps(build_agent_scorecard(base), indent=2))
