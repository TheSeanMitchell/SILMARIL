"""silmaril.portfolios.setup_classifier — Alpha 5.1 setup archetype engine.

What it does
────────────
The master directive demands every opportunity be classified into an
explicit SETUP ARCHETYPE before sizing. Generic conviction scoring is
no longer enough — the system must know:

  - Is this an EARNINGS_MOMENTUM play?
  - Is this a BREAKOUT_CONTINUATION?
  - Is this an OVERSOLD_REVERSAL?
  - Is this an INSTITUTIONAL_ACCUMULATION setup?

Each archetype has its own ideal regime, hold duration, exit style,
and historical expectancy. The conviction engine then applies a
per-archetype `setup_lift` multiplier (bounded `[0.85, 1.25]`) so the
final score reflects archetype expectancy, not just raw signal strength.

The classifier is RULE-BASED — no LLM, no paid data. It infers
archetype from inputs already in every plan:
  • signal / consensus_signal
  • catalyst_label
  • news_summary / catalyst headline keywords
  • three_month_signal + three_month_trend (uptrend / breakdown / etc.)
  • is_elite
  • volume_surge (when present)
  • short_interest (when present)

When a plan matches multiple archetypes, the most specific (highest-
priority) one wins. Every plan gets exactly one primary archetype.

Output (docs/data/setup_classifications.json)
─────────────────────────────────────────────
{
  "version": "5.1",
  "generated_at": "...",
  "archetype_stats": {
     "EARNINGS_MOMENTUM": {
        "win_rate": 0.62, "avg_return_pct": 0.034, "avg_hold_hours": 21,
        "sample_size": 8, "expectancy": 0.021,
        "best_regime": "ATTACK", "ideal_exit": "5d profit_take",
        "setup_lift": 1.12
     }, ...
  },
  "classifications": [
     {"ticker":"NVDA","archetype":"BREAKOUT_CONTINUATION",
      "lift":1.10, "rationale":"3M uptrend + STRONG_BUY + catalyst:Strong Momentum"},
     ...
  ]
}

Each plan that passes through gets a `setup_archetype` tag attached
in-place for downstream consumers (conviction_engine, dashboard).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION  = "5.1"
FILENAME = "setup_classifications.json"

# Setup archetype catalog — order matters: higher priority first wins.
ARCHETYPES: List[Dict[str, Any]] = [
    {
        "key": "EARNINGS_MOMENTUM",
        "priority": 100,
        "default_lift": 1.12,
        "ideal_hold_hours": 24,
        "ideal_exit": "swift 5d profit_take",
        "best_regime": "ATTACK",
        "catalyst_keywords": ["earnings beat", "beat estimates", "earnings surprise",
                               "raised guidance", "guidance raised", "blowout earnings",
                               "crushed estimates", "topped expectations", "tops estimates"],
        "min_signal":  "BUY",
        "label": "Earnings Momentum",
    },
    {
        "key": "POST_EARNINGS_DRIFT",
        "priority": 95,
        "default_lift": 1.06,
        "ideal_hold_hours": 96,
        "ideal_exit": "trailing stop",
        "best_regime": "BALANCED",
        "catalyst_keywords": ["post-earnings", "post earnings drift", "earnings drift",
                               "continuing higher after earnings", "drifting higher"],
        "min_signal":  "BUY",
        "label": "Post-Earnings Drift",
    },
    {
        "key": "BREAKOUT_CONTINUATION",
        "priority": 90,
        "default_lift": 1.10,
        "ideal_hold_hours": 72,
        "ideal_exit": "scale-out at +3%/+5%/+8%",
        "best_regime": "ATTACK",
        "require_uptrend":     True,
        "require_strong_buy":  False,
        "catalyst_keywords": ["breakout", "new high", "breaks out", "breaking out",
                               "fresh highs", "all-time high", "52-week high"],
        "min_signal": "BUY",
        "label": "Breakout Continuation",
    },
    {
        "key": "GAP_AND_GO",
        "priority": 85,
        "default_lift": 1.08,
        "ideal_hold_hours": 8,
        "ideal_exit": "intraday momentum exit",
        "best_regime": "ATTACK",
        "catalyst_keywords": ["gap up", "premarket surge", "premarket gain",
                               "pre-market rally", "gaps higher", "opens sharply"],
        "min_signal": "BUY",
        "label": "Gap and Go",
    },
    {
        "key": "INSTITUTIONAL_ACCUMULATION",
        "priority": 80,
        "default_lift": 1.10,
        "ideal_hold_hours": 240,
        "ideal_exit": "trailing wide",
        "best_regime": "BALANCED",
        "catalyst_keywords": ["institutional buying", "fund accumulation",
                               "block trade", "13F filing", "insider buying",
                               "form 4 buying"],
        "min_signal": "BUY",
        "label": "Institutional Accumulation",
    },
    {
        "key": "HIGH_SHORT_INTEREST_MOMENTUM",
        "priority": 75,
        "default_lift": 1.05,
        "ideal_hold_hours": 48,
        "ideal_exit": "swift profit_take",
        "best_regime": "ATTACK",
        "catalyst_keywords": ["short squeeze", "short interest", "shorts covering",
                               "squeeze in motion"],
        "min_signal": "BUY",
        "label": "Short-Squeeze Momentum",
    },
    {
        "key": "SECTOR_ROTATION_LEADER",
        "priority": 70,
        "default_lift": 1.08,
        "ideal_hold_hours": 120,
        "ideal_exit": "rotation_lift decay",
        "best_regime": "BALANCED",
        "require_strengthening_sector": True,
        "catalyst_keywords": ["sector rotation", "rotation into", "money flowing into",
                               "leadership shift"],
        "min_signal": "BUY",
        "label": "Sector Rotation Leader",
    },
    {
        "key": "NEWS_EXPANSION",
        "priority": 65,
        "default_lift": 1.04,
        "ideal_hold_hours": 36,
        "ideal_exit": "catalyst decay",
        "best_regime": "ATTACK",
        "catalyst_keywords": ["analyst upgrade", "upgraded to buy", "raised price target",
                               "fda approval", "drug approval", "merger", "acquisition",
                               "contract win", "partnership", "approved"],
        "min_signal": "BUY",
        "label": "News Expansion",
    },
    {
        "key": "OVERSOLD_REVERSAL",
        "priority": 50,
        "default_lift": 0.98,
        "ideal_hold_hours": 96,
        "ideal_exit": "mean-revert profit_take",
        "best_regime": "DEFENSIVE",
        "catalyst_keywords": ["oversold bounce", "oversold conditions", "rebound from",
                               "bottoming pattern", "rsi extreme"],
        "min_signal": "BUY",
        "label": "Oversold Reversal",
    },
    {
        "key": "DEFENSIVE_SAFEHAVEN",
        "priority": 40,
        "default_lift": 0.95,
        "ideal_hold_hours": 168,
        "ideal_exit": "regime shift exit",
        "best_regime": "DEFENSIVE",
        "catalyst_keywords": ["safe haven", "flight to quality", "defensive rotation",
                               "utilities rally", "consumer staples"],
        "min_signal": "BUY",
        "label": "Defensive Safehaven",
    },
]

LIFT_MIN = 0.85
LIFT_MAX = 1.25
# Per-archetype lift is BOUNDED so a single setup type cannot dominate.
# Compose with sector_rotation lift in conviction_engine.


def _safe_f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def _load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _norm(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).lower()).strip()


def _plan_match_corpus(plan: Dict[str, Any]) -> str:
    """Concatenate every text field on a plan into one lowercased corpus
    suitable for keyword matching."""
    bits: List[str] = []
    for k in ("catalyst_label", "catalyst_strength_label", "news_summary",
              "rationale", "signal_summary", "title", "headline"):
        v = plan.get(k)
        if v:
            bits.append(str(v))
    # Catalyst array if present
    for cat in (plan.get("catalysts") or []):
        if isinstance(cat, dict):
            for k in ("title", "headline", "text", "summary"):
                if cat.get(k):
                    bits.append(str(cat[k]))
        elif isinstance(cat, str):
            bits.append(cat)
    return _norm(" · ".join(bits))


# ── Classification ────────────────────────────────────────────────────

_SIGNAL_RANK = {"STRONG_SELL": 0, "SELL": 1, "HOLD": 2,
                  "BUY": 3, "STRONG_BUY": 4}


def _signal_meets(plan_signal: Optional[str], required: Optional[str]) -> bool:
    if not required:
        return True
    return _SIGNAL_RANK.get((plan_signal or "").upper(), -1) >= \
           _SIGNAL_RANK.get((required or "").upper(), -1)


def classify_plan(
    plan: Dict[str, Any],
    sector_rotation: Optional[Dict[str, Any]] = None,
) -> Tuple[str, float, str]:
    """Return (archetype_key, setup_lift, rationale) for a single plan.

    Falls through to "GENERIC" with lift=1.0 if no archetype claims the plan.
    """
    if not isinstance(plan, dict):
        return ("GENERIC", 1.0, "no plan provided")

    signal = (plan.get("consensus_signal") or plan.get("signal") or "").upper()
    corpus = _plan_match_corpus(plan)
    three_month = (plan.get("three_month_signal")
                    or plan.get("three_month_trend") or "").lower()
    sector = plan.get("sector") or plan.get("asset_class")
    is_elite = bool(plan.get("is_elite") or plan.get("elite_membership"))

    sector_strengthening = False
    if sector and isinstance(sector_rotation, dict):
        info = (sector_rotation.get("sectors") or {}).get(sector) or {}
        tag = (info.get("tag") or "").lower()
        sector_strengthening = tag in ("strengthening", "accelerating")

    for arch in ARCHETYPES:
        if not _signal_meets(signal, arch.get("min_signal")):
            continue
        if arch.get("require_uptrend") and "uptrend" not in three_month:
            continue
        if arch.get("require_strong_buy") and signal != "STRONG_BUY":
            continue
        if arch.get("require_strengthening_sector") and not sector_strengthening:
            continue

        kw_hit = None
        for kw in (arch.get("catalyst_keywords") or []):
            if kw and kw in corpus:
                kw_hit = kw
                break
        if kw_hit is None:
            # Allow BREAKOUT_CONTINUATION to qualify on uptrend + STRONG_BUY
            # even when no breakout keyword is present (catalyst feed is patchy).
            if arch["key"] == "BREAKOUT_CONTINUATION" and \
               "uptrend" in three_month and signal == "STRONG_BUY":
                kw_hit = "uptrend+STRONG_BUY"
            elif arch["key"] == "INSTITUTIONAL_ACCUMULATION" and is_elite \
                  and signal == "STRONG_BUY":
                kw_hit = "elite+STRONG_BUY"
            else:
                continue
        # Elite confidence boost: cap at LIFT_MAX.
        lift = float(arch["default_lift"])
        if is_elite:
            lift = min(LIFT_MAX, lift + 0.03)
        rationale = (f"{arch['label']} · matched '{kw_hit}'"
                     + (" · ELITE" if is_elite else ""))
        return (arch["key"], lift, rationale)

    # No archetype matched — neutral lift.
    return ("GENERIC", 1.0, f"no archetype match (signal={signal or '—'})")


def classify_plans(
    plans: List[Dict[str, Any]],
    sector_rotation: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Classify every plan and return a per-plan list of decisions."""
    out: List[Dict[str, Any]] = []
    for p in (plans or []):
        if not isinstance(p, dict):
            continue
        key, lift, rationale = classify_plan(p, sector_rotation=sector_rotation)
        out.append({
            "ticker":      (p.get("ticker") or "").upper(),
            "archetype":   key,
            "setup_lift":  round(max(LIFT_MIN, min(LIFT_MAX, lift)), 4),
            "rationale":   rationale,
            "signal":      (p.get("consensus_signal") or p.get("signal") or "").upper(),
            "is_elite":    bool(p.get("is_elite")),
            "sector":      p.get("sector"),
        })
        # Annotate the plan in place — back-compat: alpaca_paper.py
        # already passes unknown plan keys through unchanged.
        p["setup_archetype"] = key
        p["setup_lift"]      = round(max(LIFT_MIN, min(LIFT_MAX, lift)), 4)
        p["setup_rationale"] = rationale
    return out


# ── Archetype statistics from past trades ─────────────────────────────

def _stats_by_archetype(
    attrib: Optional[Dict[str, Any]],
    classifications: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Compute per-archetype outcome statistics from alpaca_attribution.

    The attribution module tags each closed trade with `setup_archetype`
    (Alpha 5.1+). For back-compat, if missing, we try to infer from
    catalyst_label using the same classifier on a synthesized plan stub.
    """
    stats: Dict[str, Dict[str, Any]] = {a["key"]: {
        "samples":     0,
        "wins":        0,
        "losses":      0,
        "pnl_total":   0.0,
        "hold_hours":  [],
        "label":       a["label"],
        "default_lift": a["default_lift"],
        "best_regime": a["best_regime"],
        "ideal_exit":  a["ideal_exit"],
        "ideal_hold_hours": a["ideal_hold_hours"],
    } for a in ARCHETYPES}
    if isinstance(attrib, dict):
        rows = attrib.get("orders") or attrib.get("rows") or []
        for r in rows:
            if not isinstance(r, dict):
                continue
            arche = r.get("setup_archetype")
            if not arche:
                # Back-compat: synthesize a stub plan for classification.
                stub = {
                    "consensus_signal": r.get("signal") or "BUY",
                    "catalyst_label":   r.get("catalyst_label"),
                    "three_month_signal": r.get("three_month_signal"),
                    "is_elite":         r.get("is_elite"),
                }
                arche, _, _ = classify_plan(stub)
            slot = stats.get(arche)
            if not slot:
                continue
            pnl = _safe_f(r.get("pnl") or r.get("realized_pnl") or r.get("net_pnl"))
            slot["samples"] += 1
            slot["pnl_total"] += pnl
            if pnl > 0:
                slot["wins"] += 1
            else:
                slot["losses"] += 1
            hold = _safe_f(r.get("hold_hours") or (r.get("hold_days") or 0) * 24)
            if hold > 0:
                slot["hold_hours"].append(hold)

    # Distill into archetype_stats output
    out: Dict[str, Dict[str, Any]] = {}
    for key, slot in stats.items():
        n = int(slot["samples"])
        if n > 0:
            win_rate    = slot["wins"] / float(n)
            avg_return  = slot["pnl_total"] / float(n)
            avg_hold    = (sum(slot["hold_hours"]) / float(len(slot["hold_hours"])))\
                            if slot["hold_hours"] else slot["ideal_hold_hours"]
            expectancy  = slot["pnl_total"] / float(n)
        else:
            win_rate, avg_return, avg_hold, expectancy = 0.0, 0.0, slot["ideal_hold_hours"], 0.0
        # Lift drift: with enough samples, allow the lift to shift up to
        # ±0.07 from default based on win_rate − 0.5.
        if n >= 8:
            drift = (win_rate - 0.5) * 0.14
            lift  = max(LIFT_MIN, min(LIFT_MAX, slot["default_lift"] + drift))
        else:
            lift  = slot["default_lift"]
        out[key] = {
            "label":           slot["label"],
            "sample_size":     n,
            "win_rate":        round(win_rate, 4),
            "avg_return_pct":  round(avg_return, 4),
            "avg_hold_hours":  round(avg_hold, 2),
            "expectancy":      round(expectancy, 4),
            "best_regime":     slot["best_regime"],
            "ideal_exit":      slot["ideal_exit"],
            "setup_lift":      round(lift, 4),
        }
    return out


# ── Public ────────────────────────────────────────────────────────────

def write_setup_classifications(
    data_dir: Path,
    plans: List[Dict[str, Any]],
    sector_rotation: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Classify the supplied plans + persist payload to docs/data/."""
    n_now = now or datetime.now(timezone.utc)
    classifications = classify_plans(plans, sector_rotation=sector_rotation)
    attrib = _load_json(data_dir / "alpaca_attribution.json")
    archetype_stats = _stats_by_archetype(attrib, classifications)
    # Re-apply the *empirical* lift to each classification so the conviction
    # engine reads a single coherent number.
    for c in classifications:
        stats = archetype_stats.get(c["archetype"]) or {}
        if stats:
            c["empirical_lift"] = stats.get("setup_lift", c["setup_lift"])
        else:
            c["empirical_lift"] = c["setup_lift"]

    payload = {
        "version":         VERSION,
        "generated_at":    n_now.isoformat(),
        "archetype_stats": archetype_stats,
        "classifications": classifications,
        "totals": {
            "classified":  len(classifications),
            "generic":     sum(1 for c in classifications if c["archetype"] == "GENERIC"),
            "elite":       sum(1 for c in classifications if c.get("is_elite")),
        },
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[setup_classifier] write failed: {e}")
    return payload


def get_setup_lift(
    data_dir: Path,
    archetype: Optional[str],
) -> float:
    """Return the empirical lift for an archetype. 1.0 = neutral / unknown."""
    if not archetype:
        return 1.0
    body = _load_json(data_dir / FILENAME)
    if not isinstance(body, dict):
        return 1.0
    stats = (body.get("archetype_stats") or {}).get(archetype) or {}
    v = _safe_f(stats.get("setup_lift"), 1.0)
    return max(LIFT_MIN, min(LIFT_MAX, v))


def load_setup_classifications(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "archetype_stats": {}, "classifications": []}


__all__ = [
    "VERSION", "ARCHETYPES", "LIFT_MIN", "LIFT_MAX",
    "classify_plan", "classify_plans",
    "write_setup_classifications", "get_setup_lift",
    "load_setup_classifications",
]
