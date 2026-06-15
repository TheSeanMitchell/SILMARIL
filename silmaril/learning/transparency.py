"""silmaril.learning.transparency — Alpha 5.0 learning observability layer.

What it does
────────────
The master directive flags: "we don't even know what it is learning"
as a major issue. This module is the single place the dashboard reads
to answer:

  - Which catalyst types are paying off?
  - Which sectors are doing well / poorly?
  - What hold duration is optimal?
  - Which market regime are we winning in?
  - What signal combinations have the highest recent expectancy?
  - What patterns failed recently?
  - How are the bounded-tuning parameters drifting?

It is intentionally a thin AGGREGATOR. The underlying truth lives in
several files already produced by the learning subsystem:

  - agent_beliefs.json           (Bayesian win-rate per agent)
  - tuning_state.json            (parameter_tuning proposed adjustments)
  - agent_evolution_cards.json   (per-agent leveling history)
  - alpaca_attribution.json      (per-order outcome tagging)
  - signal_validation.json       (regime/catalyst expectancy buckets)
  - reflections.json             (operator-injected reflections)

This module reads them defensively, picks the highlight bullets, and
publishes a single explainable summary to docs/data/learning_transparency.json.

Output
──────
{
  "version": "5.0",
  "generated_at": "...",
  "highlights": [
     {"label":"Best Catalyst Type","value":"FDA Approval","detail":"win-rate 0.68 across 31 samples"},
     {"label":"Weakest Sector",   "value":"Retail",   "detail":"expectancy -0.42% over last 14d"},
     {"label":"Best Hold Duration","value":"2.4 days","detail":"vs 0.7d short / 6.2d long"},
     ...
  ],
  "regime_attribution": {
     "ATTACK":       {"trades": 17, "win_rate": 0.65, "expectancy": +1.42},
     "BALANCED":     {"trades": 22, "win_rate": 0.55, "expectancy": +0.41},
     ...
  },
  "catalyst_attribution":   { "Strong Buy + Positive Narrative": {...}, ... },
  "best_hold_duration":     "2.4 days",
  "tuning_drift": [
     {"name":"BLEED_EXIT_MIN_LEGS",  "current":3, "default":4,
      "rationale":"loosened after 12 false positives"},
     ...
  ],
  "agent_leaders": [
     {"agent":"forge", "level":4, "win_rate":0.62, "trades":48}, ...
  ],
  "failure_patterns": [
     {"label":"Gap-up reversals", "samples":5, "expectancy":-2.8},
     ...
  ],
  "rationale": "..."
}

Failure modes
─────────────
If any input is missing, the corresponding highlight is omitted rather
than guessed. The dashboard can show "—" for missing fields. We never
manufacture confidence; everything is rooted in observable sample counts.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION  = "5.0"
FILENAME = "learning_transparency.json"

MIN_SAMPLES_FOR_HIGHLIGHT = 5    # smallest sample we'll claim something from


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


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


# ── Source readers ───────────────────────────────────────────────────

def _best_worst_from_signal_validation(
    sv: Optional[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Read signal_validation buckets and produce (best, worst).

    signal_validation.json shape (Alpha 4.0):
      {
        "buckets": {
          "STRONG_BUY|ATTACK|elite": {"samples": 12, "win_rate": 0.66,
                                       "expectancy": 1.42},
          ...
        }
      }
    """
    if not isinstance(sv, dict):
        return (None, None)
    buckets = sv.get("buckets") or {}
    if not buckets:
        return (None, None)
    rows: List[Dict[str, Any]] = []
    for key, b in buckets.items():
        if not isinstance(b, dict):
            continue
        n = int(b.get("samples") or 0)
        if n < MIN_SAMPLES_FOR_HIGHLIGHT:
            continue
        rows.append({
            "key":         key,
            "samples":     n,
            "win_rate":    _safe_f(b.get("win_rate")),
            "expectancy": _safe_f(b.get("expectancy")),
        })
    if not rows:
        return (None, None)
    best = max(rows, key=lambda r: r["expectancy"])
    worst = min(rows, key=lambda r: r["expectancy"])
    return (best, worst)


def _regime_attribution_from_attrib(
    attrib: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, float]]:
    """Aggregate alpaca_attribution rows by regime."""
    out: Dict[str, Dict[str, float]] = {}
    if not isinstance(attrib, dict):
        return out
    rows = attrib.get("orders") or attrib.get("rows") or []
    by_regime: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if not isinstance(r, dict):
            continue
        regime = (r.get("regime") or r.get("market_mode") or "").upper()
        if not regime:
            continue
        pnl = _safe_f(r.get("pnl") or r.get("realized_pnl") or r.get("net_pnl"))
        by_regime[regime].append({"pnl": pnl})
    for regime, lst in by_regime.items():
        if not lst:
            continue
        wins = sum(1 for x in lst if x["pnl"] > 0)
        total = len(lst)
        avg_pnl = sum(x["pnl"] for x in lst) / float(total)
        out[regime] = {
            "trades":     total,
            "win_rate":   round(wins / float(total), 4) if total else 0.0,
            "expectancy": round(avg_pnl, 4),
        }
    return out


def _sector_attribution_from_attrib(
    attrib: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(attrib, dict):
        return out
    rows = attrib.get("orders") or attrib.get("rows") or []
    by_sector: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        if not isinstance(r, dict):
            continue
        sec = r.get("sector") or "Unknown"
        pnl = _safe_f(r.get("pnl") or r.get("realized_pnl") or r.get("net_pnl"))
        by_sector[sec].append(pnl)
    for sec, pnls in by_sector.items():
        if len(pnls) < MIN_SAMPLES_FOR_HIGHLIGHT:
            continue
        total = len(pnls)
        wins = sum(1 for p in pnls if p > 0)
        out.append({
            "sector":     sec,
            "trades":     total,
            "win_rate":   round(wins / float(total), 4) if total else 0.0,
            "expectancy": round(sum(pnls) / float(total), 4),
        })
    out.sort(key=lambda r: r["expectancy"], reverse=True)
    return out


def _hold_duration_buckets(
    attrib: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, float]]:
    """Bucket by hold-duration: short (<1d), medium (1-4d), long (>4d).

    Returns {bucket: {trades, win_rate, expectancy, avg_days}}.
    """
    out: Dict[str, Dict[str, float]] = {}
    if not isinstance(attrib, dict):
        return out
    rows = attrib.get("orders") or attrib.get("rows") or []
    buckets: Dict[str, List[Tuple[float, float]]] = {
        "short (<1d)":   [], "medium (1-4d)": [], "long (>4d)":  [],
    }
    for r in rows:
        if not isinstance(r, dict):
            continue
        days = _safe_f(r.get("hold_days") or r.get("days_held"))
        pnl  = _safe_f(r.get("pnl") or r.get("realized_pnl") or r.get("net_pnl"))
        if days <= 0:
            continue
        if days < 1.0:
            key = "short (<1d)"
        elif days <= 4.0:
            key = "medium (1-4d)"
        else:
            key = "long (>4d)"
        buckets[key].append((days, pnl))
    for key, lst in buckets.items():
        if len(lst) < MIN_SAMPLES_FOR_HIGHLIGHT:
            continue
        total = len(lst)
        wins  = sum(1 for d, p in lst if p > 0)
        avg_days = sum(d for d, _ in lst) / float(total)
        avg_pnl  = sum(p for _, p in lst) / float(total)
        out[key] = {
            "trades":     total,
            "win_rate":   round(wins / float(total), 4),
            "expectancy": round(avg_pnl, 4),
            "avg_days":   round(avg_days, 2),
        }
    return out


def _agent_leaders_from_beliefs(
    beliefs: Optional[Dict[str, Any]],
    cards: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(beliefs, dict):
        return out
    agents = beliefs.get("agents") or {}
    cards_data = (cards or {}).get("cards") if isinstance(cards, dict) else {}
    for name, st in agents.items():
        if not isinstance(st, dict):
            continue
        alpha = _safe_f(st.get("alpha"), 1.0)
        beta  = _safe_f(st.get("beta"),  1.0)
        trades = int(st.get("trades") or st.get("samples") or 0)
        if trades < MIN_SAMPLES_FOR_HIGHLIGHT:
            continue
        wr = alpha / (alpha + beta) if (alpha + beta) > 0 else 0.0
        card = (cards_data or {}).get(name) or {}
        level = int(card.get("level") or 1)
        out.append({
            "agent":    name,
            "level":    level,
            "win_rate": round(wr, 4),
            "trades":   trades,
            "alpha":    round(alpha, 2),
            "beta":     round(beta, 2),
        })
    out.sort(key=lambda r: (r["win_rate"], r["trades"]), reverse=True)
    return out[:8]


def _tuning_drift_from_tuning_state(
    tuning: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(tuning, dict):
        return out
    proposed = tuning.get("proposed") or {}
    for full_key, info in (proposed.items() if isinstance(proposed, dict) else []):
        if not isinstance(info, dict):
            continue
        out.append({
            "name":        full_key,
            "current":     info.get("current"),
            "proposed":    info.get("proposed"),
            "default":     info.get("default"),
            "samples":     int(info.get("samples") or 0),
            "rationale":   info.get("rationale") or "",
        })
    out.sort(key=lambda r: r.get("samples", 0), reverse=True)
    return out[:12]


def _failure_patterns_from_attrib(
    attrib: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Identify recurring categories of failed trades."""
    out: List[Dict[str, Any]] = []
    if not isinstance(attrib, dict):
        return out
    rows = attrib.get("orders") or attrib.get("rows") or []
    by_cat: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        if not isinstance(r, dict):
            continue
        pnl = _safe_f(r.get("pnl") or r.get("realized_pnl") or r.get("net_pnl"))
        if pnl >= 0:
            continue
        cat = (r.get("close_reason") or r.get("exit_reason")
                or r.get("close_category") or "").lower().strip()
        if not cat:
            continue
        by_cat[cat].append(pnl)
    for cat, pnls in by_cat.items():
        if len(pnls) < 3:
            continue
        total = len(pnls)
        avg_pnl = sum(pnls) / float(total)
        out.append({
            "label":      cat,
            "samples":    total,
            "expectancy": round(avg_pnl, 4),
        })
    out.sort(key=lambda r: r["expectancy"])
    return out[:6]


# ── Public ───────────────────────────────────────────────────────────

def build_learning_transparency(
    data_dir: Path,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Aggregate every learning source into one explainable rollup."""
    n_now = now or datetime.now(timezone.utc)

    beliefs   = _load_json(data_dir / "agent_beliefs.json")
    cards     = _load_json(data_dir / "agent_evolution_cards.json")
    attrib    = _load_json(data_dir / "alpaca_attribution.json")
    sv        = _load_json(data_dir / "signals.json")          # may have meta
    sigval    = _load_json(data_dir / "signal_validation.json")
    tuning    = _load_json(data_dir / "tuning_state.json")

    best_bucket, worst_bucket = _best_worst_from_signal_validation(sigval)
    regime_attr = _regime_attribution_from_attrib(attrib)
    sector_attr = _sector_attribution_from_attrib(attrib)
    hold_buckets = _hold_duration_buckets(attrib)
    agent_leaders = _agent_leaders_from_beliefs(beliefs, cards)
    tuning_drift = _tuning_drift_from_tuning_state(tuning)
    failure_patterns = _failure_patterns_from_attrib(attrib)

    # Build highlight bullets
    highlights: List[Dict[str, Any]] = []
    if best_bucket:
        highlights.append({
            "label":  "Best Signal Combination",
            "value":  best_bucket["key"],
            "detail": (f"expectancy {best_bucket['expectancy']:+.2f} · "
                        f"win-rate {best_bucket['win_rate']:.2f} · "
                        f"{best_bucket['samples']} samples"),
        })
    if worst_bucket and worst_bucket.get("expectancy", 0.0) < 0:
        highlights.append({
            "label":  "Weakest Signal Combination",
            "value":  worst_bucket["key"],
            "detail": (f"expectancy {worst_bucket['expectancy']:+.2f} · "
                        f"{worst_bucket['samples']} samples"),
        })
    if regime_attr:
        best_regime = max(regime_attr.items(),
                            key=lambda kv: kv[1]["expectancy"])
        highlights.append({
            "label":  "Strongest Market Regime",
            "value":  best_regime[0],
            "detail": (f"expectancy {best_regime[1]['expectancy']:+.2f} · "
                        f"win-rate {best_regime[1]['win_rate']:.2f} · "
                        f"{best_regime[1]['trades']} trades"),
        })
        worst_regime = min(regime_attr.items(),
                            key=lambda kv: kv[1]["expectancy"])
        if worst_regime[0] != best_regime[0]:
            highlights.append({
                "label":  "Weakest Market Regime",
                "value":  worst_regime[0],
                "detail": (f"expectancy {worst_regime[1]['expectancy']:+.2f} · "
                            f"{worst_regime[1]['trades']} trades"),
            })
    if sector_attr:
        highlights.append({
            "label":  "Best Sector",
            "value":  sector_attr[0]["sector"],
            "detail": (f"expectancy {sector_attr[0]['expectancy']:+.2f} · "
                        f"{sector_attr[0]['trades']} trades"),
        })
        if len(sector_attr) > 1 and sector_attr[-1]["expectancy"] < 0:
            highlights.append({
                "label":  "Weakest Sector",
                "value":  sector_attr[-1]["sector"],
                "detail": (f"expectancy {sector_attr[-1]['expectancy']:+.2f} · "
                            f"{sector_attr[-1]['trades']} trades"),
            })
    best_hold = None
    if hold_buckets:
        best_hold_key, best_hold_data = max(
            hold_buckets.items(), key=lambda kv: kv[1]["expectancy"])
        best_hold = f"{best_hold_data['avg_days']:.1f}d ({best_hold_key})"
        highlights.append({
            "label":  "Best Hold Duration",
            "value":  best_hold,
            "detail": (f"expectancy {best_hold_data['expectancy']:+.2f} · "
                        f"win-rate {best_hold_data['win_rate']:.2f} · "
                        f"{best_hold_data['trades']} trades"),
        })
    if agent_leaders:
        leader = agent_leaders[0]
        highlights.append({
            "label":  "Top Performing Agent",
            "value":  leader["agent"],
            "detail": (f"win-rate {leader['win_rate']:.2f} · "
                        f"L{leader['level']} · "
                        f"{leader['trades']} trades"),
        })
    if failure_patterns:
        worst_fail = failure_patterns[0]
        highlights.append({
            "label":  "Recurring Failure Pattern",
            "value":  worst_fail["label"],
            "detail": (f"avg loss {worst_fail['expectancy']:+.2f} · "
                        f"{worst_fail['samples']} samples"),
        })

    rationale_bits: List[str] = []
    if highlights:
        rationale_bits.append(f"{len(highlights)} learning highlights")
    if regime_attr:
        rationale_bits.append(f"{sum(r['trades'] for r in regime_attr.values())} attributed trades")
    if tuning_drift:
        rationale_bits.append(f"{len(tuning_drift)} tuning proposals")
    rationale = " · ".join(rationale_bits) if rationale_bits else "learning warming up"

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "highlights":   highlights,
        "regime_attribution":   regime_attr,
        "sector_attribution":   sector_attr,
        "hold_duration_buckets": hold_buckets,
        "best_hold_duration":   best_hold,
        "agent_leaders":        agent_leaders,
        "tuning_drift":         tuning_drift,
        "failure_patterns":     failure_patterns,
        "rationale":            rationale,
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[learning_transparency] write failed: {e}")
    return payload


def load_learning_transparency(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "highlights": [], "regime_attribution": {},
             "sector_attribution": [], "hold_duration_buckets": {},
             "best_hold_duration": None, "agent_leaders": [],
             "tuning_drift": [], "failure_patterns": [],
             "rationale": "no learning_transparency file"}


__all__ = [
    "VERSION", "build_learning_transparency", "load_learning_transparency",
]
