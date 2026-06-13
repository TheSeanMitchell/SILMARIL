"""silmaril.portfolios.event_impact — Alpha 5.1 news → implications engine.

What it does
────────────
The narrative_tracker counts phrases. This engine takes the next step:
it converts each significant news event into a structured implication:

  - market direction bias (risk_on / risk_off)
  - sectors positively affected
  - sectors negatively affected
  - expected effect duration (single_session / multi_day / multi_week)
  - macro confidence (1d / 1w / 1mo)
  - volatility risk

This is the "real intelligence" layer the master prompt demands. It is
still DETERMINISTIC and free-tier — no LLM, no paid sentiment API. It
fuses three signals:

  1. The narrative_tracker's phrase matches per headline (we re-use it).
  2. The catalysts.json structured fields (catalyst_label, novelty).
  3. A small library of impact templates (RULE_TEMPLATES below) that
     associate canonical event phrases with their structured outcome.

Each templated rule emits a partial implication; rules that fire on
the same headline get UNIONED (sectors are concatenated, biases are
averaged, durations are MAX-merged).

Output (docs/data/event_impact.json)
────────────────────────────────────
{
  "version": "5.1",
  "generated_at": "...",
  "events": [
     {
       "title": "Wall Street pessimism grows over Iran war fears",
       "source": "rss",
       "tickers_mentioned": ["XOM","LMT"],
       "implications": {
         "risk_off_bias":          0.72,
         "risk_on_bias":           0.00,
         "sector_positive":        ["Energy","Industrials"],
         "sector_negative":        ["Technology","Consumer Discretionary"],
         "expected_effect_duration": "multi_day",
         "macro_confidence":       0.68,
         "volatility_risk":        0.74,
         "matched_rules":          ["geopolitical_escalation","oil_supply_concern"]
       }
     }, ...
  ],
  "rollup": {
     "events_processed":     12,
     "net_risk_bias":        -0.42,    # negative = net risk_off
     "dominant_duration":    "multi_day",
     "volatility_pressure":   0.58,
     "sector_pressure": {
        "Technology":          -0.42,
        "Energy":               0.48,
        ...
     }
  }
}
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION  = "5.1"
FILENAME = "event_impact.json"

MAX_EVENTS_KEPT = 40


# Duration ordering for max-merge.
_DURATION_RANK = {
    "single_session": 1, "intraday":      1,
    "multi_day":      2, "swing":         2,
    "multi_week":     3, "trend":         3,
    "multi_month":    4,
}
_DURATION_LABEL = {1: "single_session", 2: "multi_day",
                     3: "multi_week",    4: "multi_month"}


# Rule templates.
# Each rule:
#   key            unique ID
#   phrases        substrings (lowercased) — any match triggers
#   risk_off       0..1 bias toward risk-off (subtractive vs risk_on)
#   risk_on        0..1 bias toward risk-on
#   pos            sectors helped (additive +)
#   neg            sectors hurt (additive -)
#   duration       expected effect duration label
#   macro_conf     macro confidence weight (0..1)
#   vol_risk       volatility lift (0..1)
RULE_TEMPLATES: List[Dict[str, Any]] = [
    {
        "key": "geopolitical_escalation",
        "phrases": ["war fears", "missile strike", "geopolitical tension",
                     "geopolitical risk", "escalation", "iran war", "ukraine war",
                     "military strike"],
        "risk_off": 0.55, "risk_on": 0.0,
        "pos": ["Energy", "Industrials"],
        "neg": ["Technology", "Consumer Discretionary"],
        "duration": "multi_day",
        "macro_conf": 0.65,
        "vol_risk": 0.70,
    },
    {
        "key": "oil_supply_concern",
        "phrases": ["opec cut", "supply concerns", "oil rally", "crude rally",
                     "oil surge", "oil tightens"],
        "risk_off": 0.20, "risk_on": 0.0,
        "pos": ["Energy"],
        "neg": ["Consumer Discretionary"],
        "duration": "multi_week",
        "macro_conf": 0.55,
        "vol_risk": 0.35,
    },
    {
        "key": "ai_unwind",
        "phrases": ["ai cooldown", "ai pullback", "rotate out of ai",
                     "ai valuations stretched", "chip stocks fall", "semis selloff",
                     "ai bubble"],
        "risk_off": 0.30, "risk_on": 0.0,
        "pos": [],
        "neg": ["Technology"],
        "duration": "multi_day",
        "macro_conf": 0.55,
        "vol_risk": 0.40,
    },
    {
        "key": "ai_expansion",
        "phrases": ["ai rally", "ai boom", "chip demand", "data-center spending",
                     "ai capex", "gpu shortage"],
        "risk_off": 0.0, "risk_on": 0.45,
        "pos": ["Technology", "Communication Services"],
        "neg": [],
        "duration": "multi_week",
        "macro_conf": 0.60,
        "vol_risk": 0.25,
    },
    {
        "key": "fed_hawkish",
        "phrases": ["fed hawkish", "rate hike", "higher for longer",
                     "hawkish powell", "sticky inflation"],
        "risk_off": 0.50, "risk_on": 0.0,
        "pos": ["Financials", "Energy"],
        "neg": ["Technology", "Real Estate", "Utilities"],
        "duration": "multi_week",
        "macro_conf": 0.70,
        "vol_risk": 0.50,
    },
    {
        "key": "fed_dovish",
        "phrases": ["rate cut", "dovish powell", "pivot in sight",
                     "disinflation", "cooling inflation"],
        "risk_off": 0.0, "risk_on": 0.50,
        "pos": ["Technology", "Real Estate", "Consumer Discretionary"],
        "neg": [],
        "duration": "multi_week",
        "macro_conf": 0.70,
        "vol_risk": 0.30,
    },
    {
        "key": "earnings_beat",
        "phrases": ["earnings beat", "beat estimates", "earnings surprise",
                     "raised guidance", "blowout earnings", "crushed estimates"],
        "risk_off": 0.0, "risk_on": 0.20,
        "pos": [],
        "neg": [],
        "duration": "multi_day",
        "macro_conf": 0.40,
        "vol_risk": 0.20,
    },
    {
        "key": "earnings_miss",
        "phrases": ["earnings miss", "missed estimates", "cut guidance",
                     "guidance cut", "fell short of estimates"],
        "risk_off": 0.20, "risk_on": 0.0,
        "pos": [],
        "neg": [],
        "duration": "multi_day",
        "macro_conf": 0.40,
        "vol_risk": 0.30,
    },
    {
        "key": "fda_approval",
        "phrases": ["fda approval", "drug approval", "trial results positive",
                     "phase 3 success"],
        "risk_off": 0.0, "risk_on": 0.25,
        "pos": ["Health Care"],
        "neg": [],
        "duration": "multi_week",
        "macro_conf": 0.55,
        "vol_risk": 0.25,
    },
    {
        "key": "credit_stress",
        "phrases": ["credit stress", "margin call", "funding stress",
                     "liquidity crisis", "credit crunch"],
        "risk_off": 0.65, "risk_on": 0.0,
        "pos": ["Utilities", "Consumer Staples"],
        "neg": ["Financials", "Real Estate"],
        "duration": "multi_week",
        "macro_conf": 0.75,
        "vol_risk": 0.80,
    },
    {
        "key": "retail_weakness",
        "phrases": ["retail sales miss", "consumer pulls back",
                     "consumer weakness", "discretionary spending falls"],
        "risk_off": 0.25, "risk_on": 0.0,
        "pos": ["Consumer Staples"],
        "neg": ["Consumer Discretionary"],
        "duration": "multi_week",
        "macro_conf": 0.55,
        "vol_risk": 0.30,
    },
    {
        "key": "defensive_flight",
        "phrases": ["flight to quality", "safe haven", "haven assets",
                     "flight to safety"],
        "risk_off": 0.50, "risk_on": 0.0,
        "pos": ["Utilities", "Consumer Staples", "Health Care"],
        "neg": ["Technology", "Consumer Discretionary"],
        "duration": "multi_day",
        "macro_conf": 0.60,
        "vol_risk": 0.55,
    },
]


def _safe_f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def _norm(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).lower()).strip()


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def classify_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Produce structured implications for a single news event."""
    title = _norm(event.get("title") or event.get("headline") or event.get("text")
                  or event.get("note") or event.get("type"))
    matched: List[str] = []
    risk_off, risk_on = 0.0, 0.0
    pos, neg = [], []
    duration_rank = 0
    macro_conf_sum, macro_conf_n = 0.0, 0
    vol_risk_sum,   vol_risk_n   = 0.0, 0

    if not title:
        return {
            "risk_off_bias":            0.0, "risk_on_bias": 0.0,
            "sector_positive":          [], "sector_negative": [],
            "expected_effect_duration": "single_session",
            "macro_confidence":         0.0, "volatility_risk": 0.0,
            "matched_rules":            [],
        }

    for rule in RULE_TEMPLATES:
        for phrase in rule.get("phrases", []):
            if phrase and phrase in title:
                matched.append(rule["key"])
                risk_off += _safe_f(rule.get("risk_off"))
                risk_on  += _safe_f(rule.get("risk_on"))
                for s in (rule.get("pos") or []):
                    if s not in pos:
                        pos.append(s)
                for s in (rule.get("neg") or []):
                    if s not in neg:
                        neg.append(s)
                dr = _DURATION_RANK.get((rule.get("duration") or "").lower(), 1)
                if dr > duration_rank:
                    duration_rank = dr
                macro_conf_sum += _safe_f(rule.get("macro_conf"))
                macro_conf_n   += 1
                vol_risk_sum   += _safe_f(rule.get("vol_risk"))
                vol_risk_n     += 1
                break  # one rule once per event

    duration = _DURATION_LABEL.get(duration_rank, "single_session")
    return {
        "risk_off_bias":            round(_clamp(risk_off), 4),
        "risk_on_bias":             round(_clamp(risk_on), 4),
        "sector_positive":          pos,
        "sector_negative":          neg,
        "expected_effect_duration": duration,
        "macro_confidence":         round(macro_conf_sum / macro_conf_n, 4)
                                        if macro_conf_n else 0.0,
        "volatility_risk":          round(vol_risk_sum / vol_risk_n, 4)
                                        if vol_risk_n else 0.0,
        "matched_rules":            matched,
    }


def build_event_impact(
    data_dir: Path,
    catalysts: Optional[List[Dict[str, Any]]] = None,
    signals: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Classify each event and build a system-wide rollup."""
    n_now = now or datetime.now(timezone.utc)
    if catalysts is None:
        doc = _load_json(data_dir / "catalysts.json") or {}
        catalysts = ((doc.get("daily") or []) + (doc.get("weekly") or [])
                     or doc.get("catalysts") or doc.get("rows") or []) \
                     if isinstance(doc, dict) else []

    events_out: List[Dict[str, Any]] = []
    sector_pressure: Dict[str, float] = {}
    net_risk_off = 0.0
    net_risk_on  = 0.0
    durations: List[int] = []
    vol_risks: List[float] = []
    rules_fired = 0

    # Catalysts
    for c in (catalysts or []):
        if not isinstance(c, dict):
            continue
        impl = classify_event(c)
        if not impl["matched_rules"]:
            continue   # only keep rule-matched events
        rules_fired += len(impl["matched_rules"])
        # Per-sector pressure: pos sectors += avg(risk_on+macro), neg sectors -= avg(risk_off+macro)
        weight = 0.5 * (impl["risk_off_bias"] + impl["risk_on_bias"]) + \
                  0.5 * impl["macro_confidence"]
        for s in impl["sector_positive"]:
            sector_pressure[s] = sector_pressure.get(s, 0.0) + 0.6 * weight
        for s in impl["sector_negative"]:
            sector_pressure[s] = sector_pressure.get(s, 0.0) - 0.6 * weight
        net_risk_off += impl["risk_off_bias"]
        net_risk_on  += impl["risk_on_bias"]
        durations.append(_DURATION_RANK.get(impl["expected_effect_duration"], 1))
        vol_risks.append(impl["volatility_risk"])
        events_out.append({
            "title":              (c.get("title") or c.get("headline") or c.get("note") or "")[:200],
            "source":             c.get("source") or c.get("publisher") or "",
            "tickers_mentioned":  list(filter(None, [
                                      (c.get("ticker") or c.get("symbol") or "").upper()
                                  ])),
            "implications":       impl,
        })

    events_out = events_out[-MAX_EVENTS_KEPT:]

    # Clamp sector pressure
    for s, v in list(sector_pressure.items()):
        sector_pressure[s] = round(_clamp(v, -1.0, 1.0), 4)
    # Dominant duration
    if durations:
        dom = max(durations)
        dominant_duration = _DURATION_LABEL.get(dom, "single_session")
    else:
        dominant_duration = "single_session"
    net_risk_bias = round(_clamp(net_risk_on - net_risk_off, -1.0, 1.0), 4)
    vol_pressure  = round(sum(vol_risks) / len(vol_risks), 4) if vol_risks else 0.0

    rollup = {
        "events_processed":     len(events_out),
        "rules_fired":          rules_fired,
        "net_risk_bias":        net_risk_bias,
        "net_risk_off":         round(_clamp(net_risk_off, 0.0, 5.0), 4),
        "net_risk_on":          round(_clamp(net_risk_on, 0.0, 5.0), 4),
        "dominant_duration":    dominant_duration,
        "volatility_pressure":  vol_pressure,
        "sector_pressure":      sector_pressure,
    }

    bits: List[str] = []
    if events_out:
        bits.append(f"{len(events_out)} events classified")
    if net_risk_bias < -0.20:
        bits.append(f"net risk-off {net_risk_bias:+.2f}")
    elif net_risk_bias > 0.20:
        bits.append(f"net risk-on {net_risk_bias:+.2f}")
    if vol_pressure >= 0.40:
        bits.append(f"vol pressure {vol_pressure:.2f}")
    rationale = " · ".join(bits) or "no rule-matched events"

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "events":       events_out,
        "rollup":       rollup,
        "rationale":    rationale,
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[event_impact] write failed: {e}")
    return payload


def load_event_impact(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "events": [],
             "rollup": {"events_processed": 0, "net_risk_bias": 0.0,
                          "dominant_duration": "single_session",
                          "volatility_pressure": 0.0, "sector_pressure": {}},
             "rationale": "no event_impact file"}


__all__ = [
    "VERSION", "RULE_TEMPLATES",
    "classify_event", "build_event_impact", "load_event_impact",
]
