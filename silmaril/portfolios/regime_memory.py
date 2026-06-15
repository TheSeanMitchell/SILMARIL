"""silmaril.portfolios.regime_memory — Alpha 5.1 rolling regime memory.

What it does
────────────
The current `market_state.py` only emits ATTACK / BALANCED / DEFENSIVE /
PRESERVATION. The master directive demands the system understand the
14-state regime taxonomy:

    rotational_bull, narrow_leadership, broad_participation,
    recession_fear, inflation_fear, liquidity_squeeze,
    ai_bubble_expansion, ai_unwind, energy_expansion,
    defensive_flight, commodity_inflation, geopolitical_escalation,
    election_uncertainty, earnings_season_aggression

These don't replace ATTACK/BALANCED/DEFENSIVE/PRESERVATION (those remain
the EXECUTION posture). Instead, they describe the macro ENVIRONMENT we
are operating inside, and they PERSIST across cycles — a regime that has
held for 5 days carries more weight than one that flipped this cycle.

This engine reads narrative_tracker.sector_pressure + market_state +
volatility regime + breadth proxies to classify the current environment
into one or more of the 14 regimes, with persistence + confidence.

It writes a rolling window so operators can SEE the system's
understanding evolve over time, instead of guessing whether the system
"remembers" what kind of market it is in.

Output (docs/data/regime_memory.json)
─────────────────────────────────────
{
  "version": "5.1",
  "generated_at": "...",
  "current_regimes": [
     {"key":"ai_unwind","label":"AI Unwind","confidence":0.62,
      "persistence_cycles":4,"trigger":"narrative.ai_cooldown=0.71"},
     {"key":"energy_expansion","label":"Energy Expansion","confidence":0.55,
      "persistence_cycles":3,"trigger":"narrative.oil_rally=0.58"},
  ],
  "regime_states": {
     "rotational_bull":           {"active": true,  "persistence": 5, "confidence": 0.58},
     "narrow_leadership":         {"active": false, "persistence": 0, "confidence": 0.0},
     "broad_participation":       {"active": false, "persistence": 0, "confidence": 0.0},
     "recession_fear":            {"active": false, ...},
     "inflation_fear":            ...,
     "liquidity_squeeze":         ...,
     "ai_bubble_expansion":       ...,
     "ai_unwind":                 ...,
     "energy_expansion":          ...,
     "defensive_flight":          ...,
     "commodity_inflation":       ...,
     "geopolitical_escalation":   ...,
     "election_uncertainty":      ...,
     "earnings_season_aggression":...
  },
  "summary": {
     "active_regimes":        3,
     "dominant_regime":       "ai_unwind",
     "stability_score":       0.78,    # how stable is the regime state right now
     "transition_pressure":   0.22     # pressure for a regime change
  },
  "history": [...]
}
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


VERSION  = "5.1"
FILENAME = "regime_memory.json"

MAX_HISTORY = 90    # ≈3 months at one cycle/day
CONFIDENCE_THRESHOLD = 0.40   # below this, regime is considered inactive
PERSISTENCE_DECAY = 1         # how much persistence decays per inactive cycle


# Regime classification rules. Each rule emits a confidence in [0,1].
# A rule can read any combination of inputs; the engine wires them up.
REGIMES: List[Dict[str, Any]] = [
    {"key": "rotational_bull",            "label": "Rotational Bull"},
    {"key": "narrow_leadership",          "label": "Narrow Leadership"},
    {"key": "broad_participation",        "label": "Broad Participation"},
    {"key": "recession_fear",             "label": "Recession Fear"},
    {"key": "inflation_fear",             "label": "Inflation Fear"},
    {"key": "liquidity_squeeze",          "label": "Liquidity Squeeze"},
    {"key": "ai_bubble_expansion",        "label": "AI Bubble Expansion"},
    {"key": "ai_unwind",                  "label": "AI Unwind"},
    {"key": "energy_expansion",           "label": "Energy Expansion"},
    {"key": "defensive_flight",           "label": "Defensive Flight"},
    {"key": "commodity_inflation",        "label": "Commodity Inflation"},
    {"key": "geopolitical_escalation",    "label": "Geopolitical Escalation"},
    {"key": "election_uncertainty",       "label": "Election Uncertainty"},
    {"key": "earnings_season_aggression", "label": "Earnings Season Aggression"},
]


def _safe_f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _score_regimes(
    narrative: Optional[Dict[str, Any]],
    sector_rotation: Optional[Dict[str, Any]],
    market_state: Optional[Dict[str, Any]],
    catalysts: Optional[List[Dict[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    """Score each of the 14 regimes from inputs. 0..1 confidence each."""
    narrative  = narrative  or {}
    sec_rot    = sector_rotation or {}
    ms         = market_state or {}
    sec_pres   = narrative.get("sector_pressure") or {}
    narratives = narrative.get("narratives") or {}
    sectors    = sec_rot.get("sectors") or {}
    vix        = _safe_f(ms.get("vix"))
    regime     = (ms.get("regime") or "").lower()
    mode       = (ms.get("mode") or "").upper()

    # Pull narrative score helpers
    def n(key: str) -> float:
        return _safe_f((narratives.get(key) or {}).get("score"))

    # Sector flow helper
    def sf(name: str) -> float:
        return _safe_f((sectors.get(name) or {}).get("flow_score"))

    # Catalyst presence helper — does the corpus contain any of these substrings?
    cat_corpus = ""
    if catalysts:
        cat_corpus = " ".join(str((c or {}).get("title") or "").lower()
                                for c in catalysts if isinstance(c, dict))

    def cat_has(*needles: str) -> int:
        n_hits = 0
        for x in needles:
            if x and x in cat_corpus:
                n_hits += 1
        return n_hits

    scores: Dict[str, float] = {}

    # 1. Rotational bull — mix of risk_on narratives + multiple sector rotations
    risk_on  = n("risk_on") + n("fed_dovish")
    rotation_signals = sum(1 for s in sectors.values()
                              if _safe_f(s.get("flow_score")) >= 0.25)
    scores["rotational_bull"] = _clamp(
        0.45 * risk_on + 0.10 * min(rotation_signals, 4)
    )

    # 2. Narrow leadership — only 1-2 sectors strong, the rest weak/neutral
    strong = sum(1 for s in sectors.values() if _safe_f(s.get("flow_score")) >= 0.30)
    weak   = sum(1 for s in sectors.values() if _safe_f(s.get("flow_score")) <= -0.15)
    if strong > 0 and strong <= 2 and len(sectors) >= 6:
        scores["narrow_leadership"] = _clamp(
            0.45 + 0.10 * (weak - 1) - 0.05 * (strong - 1)
        )
    else:
        scores["narrow_leadership"] = 0.0

    # 3. Broad participation — many sectors positive
    if strong >= 5:
        scores["broad_participation"] = _clamp(0.40 + 0.05 * strong)
    else:
        scores["broad_participation"] = 0.0

    # 4. Recession fear
    scores["recession_fear"] = _clamp(
        0.50 * n("risk_off")
        + 0.30 * (1.0 if vix >= 25 else 0.0)
        + 0.20 * min(1.0, cat_has("recession", "slowdown", "contraction") / 2.0)
    )

    # 5. Inflation fear
    scores["inflation_fear"] = _clamp(
        0.40 * n("fed_hawkish")
        + 0.30 * min(1.0, cat_has("inflation", "cpi hot", "sticky inflation",
                                    "consumer prices") / 2.0)
        + 0.15 * (1.0 if sf("Energy") > 0.20 else 0.0)
    )

    # 6. Liquidity squeeze
    scores["liquidity_squeeze"] = _clamp(
        0.30 * n("fed_hawkish")
        + 0.40 * (1.0 if vix >= 30 else 0.0)
        + 0.20 * min(1.0, cat_has("liquidity", "credit stress", "margin call",
                                    "funding stress") / 2.0)
    )

    # 7. AI bubble expansion
    scores["ai_bubble_expansion"] = _clamp(
        0.55 * n("ai_rally") + 0.25 * (1.0 if sf("Technology") >= 0.25 else 0.0)
    )

    # 8. AI unwind
    scores["ai_unwind"] = _clamp(
        0.65 * n("ai_cooldown") + 0.20 * (1.0 if sf("Technology") <= -0.20 else 0.0)
    )

    # 9. Energy expansion
    scores["energy_expansion"] = _clamp(
        0.55 * n("oil_rally") + 0.25 * (1.0 if sf("Energy") >= 0.25 else 0.0)
    )

    # 10. Defensive flight
    scores["defensive_flight"] = _clamp(
        0.40 * n("risk_off") + 0.25 * max(0.0, sf("Consumer Staples"))
        + 0.20 * max(0.0, sf("Utilities"))
    )

    # 11. Commodity inflation
    scores["commodity_inflation"] = _clamp(
        0.30 * n("oil_rally")
        + 0.30 * min(1.0, cat_has("commodity", "metals rally", "gold rally",
                                    "copper rally") / 2.0)
        + 0.15 * (1.0 if sf("Materials") >= 0.20 else 0.0)
    )

    # 12. Geopolitical escalation
    scores["geopolitical_escalation"] = _clamp(
        0.50 * n("defense_strength")
        + 0.30 * min(1.0, cat_has("war", "missile", "strike", "escalation",
                                    "geopolitical") / 2.0)
    )

    # 13. Election uncertainty (calendar-aware: only fires near Nov / primaries)
    election_window = False
    try:
        now_dt = datetime.now(timezone.utc)
        # Treat Aug-Nov of an even-numbered (US-federal) year as active.
        if now_dt.month in (8, 9, 10, 11) and now_dt.year % 2 == 0:
            election_window = True
    except Exception:
        pass
    scores["election_uncertainty"] = _clamp(
        (0.30 if election_window else 0.05)
        + 0.40 * min(1.0, cat_has("election", "vote", "primary", "polling") / 2.0)
        + 0.10 * (1.0 if vix >= 22 else 0.0)
    )

    # 14. Earnings season aggression (calendar-aware: Jan, Apr, Jul, Oct)
    earnings_window = False
    try:
        now_dt = datetime.now(timezone.utc)
        if now_dt.month in (1, 4, 7, 10):
            earnings_window = True
    except Exception:
        pass
    scores["earnings_season_aggression"] = _clamp(
        (0.30 if earnings_window else 0.05)
        + 0.35 * min(1.0, cat_has("earnings beat", "beat estimates", "earnings miss",
                                    "guidance raised") / 2.0)
        + 0.10 * (1.0 if mode == "ATTACK" else 0.0)
    )

    # Wrap each into a uniform dict
    out: Dict[str, Dict[str, Any]] = {}
    for r in REGIMES:
        k = r["key"]
        out[k] = {
            "label":      r["label"],
            "confidence": round(scores.get(k, 0.0), 4),
        }
    return out


# ── Public API ────────────────────────────────────────────────────────

def update_regime_memory(
    data_dir: Path,
    narrative: Optional[Dict[str, Any]] = None,
    sector_rotation: Optional[Dict[str, Any]] = None,
    market_state: Optional[Dict[str, Any]] = None,
    catalysts: Optional[List[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Score regimes for this cycle, update persistence, persist + return."""
    n_now = now or datetime.now(timezone.utc)
    if narrative is None:
        narrative = _load_json(data_dir / "narrative_tracker.json") or {}
    if sector_rotation is None:
        sector_rotation = _load_json(data_dir / "sector_rotation.json") or {}
    if market_state is None:
        market_state = _load_json(data_dir / "market_state.json") or {}
    if catalysts is None:
        cats_doc = _load_json(data_dir / "catalysts.json") or {}
        catalysts = ((cats_doc.get("daily") or []) + (cats_doc.get("weekly") or [])
                     or cats_doc.get("catalysts") or cats_doc.get("rows") or []) \
                    if isinstance(cats_doc, dict) else []

    scored = _score_regimes(narrative, sector_rotation, market_state, catalysts)
    prior = _load_json(data_dir / FILENAME) or {}
    prior_states = (prior.get("regime_states") or {}) if isinstance(prior, dict) else {}

    # Combine score + persistence
    regime_states: Dict[str, Dict[str, Any]] = {}
    for r in REGIMES:
        k = r["key"]
        s = scored[k]
        confidence = float(s["confidence"])
        active = confidence >= CONFIDENCE_THRESHOLD
        prior_p = int((prior_states.get(k) or {}).get("persistence", 0))
        if active:
            persistence = min(MAX_HISTORY, prior_p + 1)
        else:
            persistence = max(0, prior_p - PERSISTENCE_DECAY)
        regime_states[k] = {
            "label":       r["label"],
            "active":      bool(active),
            "confidence":  round(confidence, 4),
            "persistence": persistence,
        }

    active_list = [
        {"key": k, "label": v["label"], "confidence": v["confidence"],
         "persistence_cycles": v["persistence"]}
        for k, v in regime_states.items() if v["active"]
    ]
    active_list.sort(key=lambda d: (d["persistence_cycles"], d["confidence"]),
                       reverse=True)

    dominant_key = active_list[0]["key"] if active_list else ""
    # Stability: how many regimes turned over since last cycle?
    prior_active = {k for k, v in prior_states.items() if v.get("active")}
    new_active   = {k for k, v in regime_states.items() if v["active"]}
    if prior_active or new_active:
        churn = len(prior_active ^ new_active) / float(max(1, len(prior_active | new_active)))
        stability = round(1.0 - churn, 4)
    else:
        stability = 1.0
    transition_pressure = round(1.0 - stability, 4)

    history = list(prior.get("history") or []) if isinstance(prior, dict) else []
    history.append({
        "cycle_ts":        n_now.isoformat(),
        "dominant_regime": dominant_key,
        "active_count":    len(active_list),
        "stability":       stability,
    })
    history = history[-MAX_HISTORY:]

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "current_regimes": active_list,
        "regime_states":   regime_states,
        "summary": {
            "active_regimes":       len(active_list),
            "dominant_regime":      dominant_key,
            "stability_score":      stability,
            "transition_pressure":  transition_pressure,
        },
        "history":      history,
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[regime_memory] write failed: {e}")
    return payload


def load_regime_memory(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "current_regimes": [], "regime_states": {},
             "summary": {"active_regimes": 0, "dominant_regime": "",
                         "stability_score": 1.0, "transition_pressure": 0.0},
             "history": []}


__all__ = [
    "VERSION", "REGIMES",
    "update_regime_memory", "load_regime_memory",
]
