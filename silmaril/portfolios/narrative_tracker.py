"""silmaril.portfolios.narrative_tracker — Alpha 5.0 deterministic narrative engine.

What it does
────────────
The master directive identifies "catalyst interpretation is still primitive"
as one of the largest current failures. This module replaces shallow keyword
scoring with a *deterministic narrative tracker* that:

  - Extracts canonical narrative phrases from news/catalyst headlines.
  - Scores each narrative on three independent axes:
      • frequency        — how many distinct sources / articles cite it
      • persistence      — how many recent cycles have echoed it
      • acceleration     — how fast frequency is growing vs the prior window
  - Maps each narrative to one or more sectors so downstream engines can
    translate "AI cooldown" into "underweight AI, overweight Defense".
  - Aggregates a single `dominant_narrative` per cycle and a `regime_shift`
    classification (RISK_ON / RISK_OFF / ROTATION / NEUTRAL).

This is INTENTIONALLY rule-based:
  - No LLM call.
  - No paid API.
  - Pure phrase counting + sector co-occurrence + simple time-decay.

The goal is "explainable narrative awareness", not magic-AI sentiment.
Operators can look at the JSON and see the exact phrases counted.

Output (docs/data/narrative_tracker.json)
─────────────────────────────────────────
{
  "version": "5.0",
  "generated_at": "...",
  "cycles_observed":         12,           # rolling history length
  "dominant_narrative":      "ai_cooldown",
  "regime_shift":            "ROTATION",
  "regime_shift_confidence": 0.62,
  "narratives": {
     "ai_cooldown": {
        "label":        "AI rally cooling",
        "sectors_into": [],
        "sectors_out":  ["Technology"],
        "frequency":      8,
        "persistence":    5,
        "acceleration":   0.42,
        "score":          0.71,
        "phrases":       ["ai cooldown", "ai rally cooling", "...stretched"],
        "matched_articles": [
           {"ticker":"NVDA","title":"...","source":"google_rss"}, ...]
     },
     "oil_rally":   { ... },
     ...
  },
  "sector_pressure": {
     "Technology":     -0.42,
     "Energy":         +0.38,
     "Defense":        +0.25,
     "Financials":      0.0,
     ...
  },
  "history": [
    {"cycle_ts":"...","dominant_narrative":"ai_cooldown","score":0.71}, ...
  ]
}

The narratives + their sector mappings are defined in `NARRATIVE_RULES`
below. Adding a narrative is a single dict append — no code changes.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


VERSION   = "5.0"
FILENAME  = "narrative_tracker.json"
MAX_HISTORY  = 60          # keep rolling 60 cycles
MAX_PHRASE_SAMPLES = 6     # cap stored phrase samples per narrative
MAX_ARTICLE_SAMPLES = 10   # cap stored article samples per narrative

# Score weights for the composite narrative score (sum ≤ 1.0).
W_FREQUENCY     = 0.45
W_PERSISTENCE   = 0.35
W_ACCELERATION  = 0.20


# ── Narrative rule table ────────────────────────────────────────────
# Each rule:
#   key            unique narrative ID (snake_case)
#   label          human-readable description
#   phrases        list of regex-friendly substrings (lowercased)
#                  any one match counts as a hit
#   sectors_into   sectors the rotation FAVOURS
#   sectors_out    sectors the rotation HURTS
#   regime_bias    "RISK_ON" / "RISK_OFF" / "ROTATION" / "NEUTRAL"
#
# Phrases are lowercased + stripped before matching. No regex magic;
# we use plain `in` substring matching for determinism and auditability.
NARRATIVE_RULES: List[Dict[str, Any]] = [
    # ── Risk-on / risk-off ──────────────────────────────────────────
    {
        "key": "risk_on",
        "label": "Risk-on sentiment returning",
        "phrases": [
            "risk-on", "risk on sentiment", "appetite for risk",
            "rally continues", "buying the dip", "soft landing",
            "broad-based rally", "all-time high",
        ],
        "sectors_into": ["Technology", "Consumer Discretionary", "Communication Services"],
        "sectors_out":  ["Consumer Staples", "Utilities"],
        "regime_bias":  "RISK_ON",
    },
    {
        "key": "risk_off",
        "label": "Risk-off / safe-haven buying",
        "phrases": [
            "risk-off", "risk off", "safe haven", "safe-haven",
            "flight to safety", "flight-to-quality", "haven assets",
            "investors flee", "fleeing risk", "selloff deepens",
        ],
        "sectors_into": ["Consumer Staples", "Utilities", "Health Care"],
        "sectors_out":  ["Technology", "Consumer Discretionary"],
        "regime_bias":  "RISK_OFF",
    },

    # ── AI / Technology ─────────────────────────────────────────────
    {
        "key": "ai_rally",
        "label": "AI / Tech rally accelerating",
        "phrases": [
            "ai rally", "ai boom", "ai surge", "ai-driven gains",
            "chip demand", "data-center spending", "gpu shortage",
            "ai capex", "model training",
        ],
        "sectors_into": ["Technology"],
        "sectors_out":  [],
        "regime_bias":  "RISK_ON",
    },
    {
        "key": "ai_cooldown",
        "label": "AI rally cooling / stretched valuations",
        "phrases": [
            "ai cooldown", "ai cooling", "ai rally cooling",
            "ai bubble", "ai valuations stretched",
            "rotate out of ai", "rotating out of ai",
            "ai pullback", "chip stocks fall", "semis selloff",
        ],
        "sectors_into": [],
        "sectors_out":  ["Technology"],
        "regime_bias":  "ROTATION",
    },

    # ── Energy / Oil ────────────────────────────────────────────────
    {
        "key": "oil_rally",
        "label": "Oil & energy strengthening",
        "phrases": [
            "oil rally", "oil surge", "oil prices jump",
            "crude rally", "crude jumps", "energy rally",
            "opec cut", "opec+", "supply concerns",
            "war fears boosting oil", "geopolitical premium",
        ],
        "sectors_into": ["Energy"],
        "sectors_out":  [],
        "regime_bias":  "ROTATION",
    },
    {
        "key": "oil_weakness",
        "label": "Oil / energy weakening",
        "phrases": [
            "oil slump", "oil falls", "oil tumbles",
            "crude weakness", "demand worries",
            "energy stocks fall",
        ],
        "sectors_into": [],
        "sectors_out":  ["Energy"],
        "regime_bias":  "NEUTRAL",
    },

    # ── Defense ─────────────────────────────────────────────────────
    {
        "key": "defense_strength",
        "label": "Defense / aerospace strengthening on geopolitical risk",
        "phrases": [
            "defense rally", "defense stocks rise",
            "geopolitical tension", "geopolitical risk",
            "war fears", "missile strike", "military spending",
            "pentagon contract", "defense contract",
        ],
        "sectors_into": ["Industrials"],
        "sectors_out":  [],
        "regime_bias":  "ROTATION",
    },

    # ── Healthcare / Biotech ────────────────────────────────────────
    {
        "key": "biotech_breakout",
        "label": "Biotech / pharma breakout",
        "phrases": [
            "biotech rally", "biotech breakout", "biotech surge",
            "fda approval", "trial results positive", "phase 3 success",
            "drug approval", "pharma deal",
        ],
        "sectors_into": ["Health Care"],
        "sectors_out":  [],
        "regime_bias":  "ROTATION",
    },

    # ── Consumer / Retail ──────────────────────────────────────────
    {
        "key": "retail_weakness",
        "label": "Retail / discretionary weakness",
        "phrases": [
            "retail sales miss", "consumer pulls back",
            "consumer weakness", "retailers cut guidance",
            "discretionary spending falls",
        ],
        "sectors_into": [],
        "sectors_out":  ["Consumer Discretionary"],
        "regime_bias":  "ROTATION",
    },

    # ── Fed / Macro ────────────────────────────────────────────────
    {
        "key": "fed_hawkish",
        "label": "Fed hawkish / rate-hike fears",
        "phrases": [
            "fed hawkish", "rate hike", "rate hikes",
            "hawkish powell", "fed fears", "higher for longer",
            "inflation persists", "sticky inflation",
        ],
        "sectors_into": ["Financials"],
        "sectors_out":  ["Technology", "Real Estate", "Utilities"],
        "regime_bias":  "RISK_OFF",
    },
    {
        "key": "fed_dovish",
        "label": "Fed dovish / rate-cut expectations",
        "phrases": [
            "fed dovish", "rate cut", "rate cuts",
            "dovish powell", "pivot in sight",
            "disinflation", "cooling inflation",
        ],
        "sectors_into": ["Technology", "Consumer Discretionary", "Real Estate"],
        "sectors_out":  [],
        "regime_bias":  "RISK_ON",
    },

    # ── Generic rotation phrases ───────────────────────────────────
    {
        "key": "rotation_explicit",
        "label": "Explicit rotation language in headlines",
        "phrases": [
            "money rotating", "rotation into", "rotation out of",
            "money flowing into", "money flowing out of",
            "rotating capital", "rotation trade",
        ],
        "sectors_into": [],
        "sectors_out":  [],
        "regime_bias":  "ROTATION",
    },
]


# Sector universe used for the sector_pressure rollup; new sectors are
# added automatically the first time they appear in a NARRATIVE_RULES row.
_BASE_SECTORS = (
    "Technology", "Energy", "Industrials", "Health Care", "Financials",
    "Consumer Discretionary", "Consumer Staples", "Communication Services",
    "Real Estate", "Utilities", "Materials",
)


# ─── Helpers ───────────────────────────────────────────────────────

def _safe_f(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if v != v:
            return default
        return v
    except Exception:
        return default


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize(text: Optional[str]) -> str:
    if not text:
        return ""
    s = str(text).lower()
    # Collapse whitespace + strip leading/trailing punctuation noise.
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _load_json(path: Path) -> Optional[Any]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _gather_headlines(
    catalysts: Optional[List[Dict[str, Any]]],
    signals: Optional[Dict[str, Any]],
    extra_headlines: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Flatten every headline-bearing structure we can find into one list of
    {ticker, title, source} rows.  Defensive: any missing field is ''."""
    rows: List[Dict[str, Any]] = []
    for src_list in (catalysts, extra_headlines):
        if not src_list:
            continue
        for c in src_list:
            if not isinstance(c, dict):
                continue
            title = c.get("title") or c.get("headline") or c.get("text") or c.get("note") or ""
            ticker = (c.get("ticker") or c.get("symbol") or "").upper()
            source = c.get("source") or c.get("publisher") or "catalysts"
            if title:
                rows.append({"ticker": ticker, "title": title, "source": source})
    # Pull news from signals.debates[*].news if present.
    if isinstance(signals, dict):
        for d in (signals.get("debates") or []):
            if not isinstance(d, dict):
                continue
            tkr = (d.get("ticker") or "").upper()
            for n in (d.get("recent_headlines") or d.get("news") or d.get("headlines") or []):
                if isinstance(n, dict):
                    title = n.get("title") or n.get("headline") or ""
                    src = n.get("source") or n.get("publisher") or "rss"
                    if title:
                        rows.append({"ticker": tkr, "title": title, "source": src})
                elif isinstance(n, str):
                    rows.append({"ticker": tkr, "title": n, "source": "rss"})
    return rows


def _score_narrative(
    frequency: int, persistence: int, acceleration: float,
) -> float:
    """Composite 0..1 narrative score.

    frequency        — number of distinct hits THIS cycle (saturates @ 6)
    persistence      — number of recent cycles narrative has hit (out of MAX_HISTORY)
    acceleration     — (this_freq - prior_freq) / max(1, prior_freq), clamped to [-1, +1]
    """
    f_norm = min(1.0, frequency / 6.0)
    p_norm = min(1.0, persistence / 8.0)        # 8 cycles = full credit
    a_norm = max(0.0, min(1.0, (acceleration + 0.25) / 1.25))
    score = (
        W_FREQUENCY    * f_norm
        + W_PERSISTENCE * p_norm
        + W_ACCELERATION * a_norm
    )
    return round(max(0.0, min(1.0, score)), 4)


def _classify_regime_shift(
    scored: Dict[str, Dict[str, Any]],
) -> Tuple[str, float, str]:
    """Pick a regime_shift label from the strongest narratives.

    Returns (regime_shift, confidence, dominant_narrative_key).
    """
    if not scored:
        return ("NEUTRAL", 0.0, "")
    # Aggregate score by regime_bias bucket.
    buckets: Dict[str, float] = {"RISK_ON": 0.0, "RISK_OFF": 0.0,
                                  "ROTATION": 0.0, "NEUTRAL": 0.0}
    dom_key = ""
    dom_score = 0.0
    for key, n in scored.items():
        s = float(n.get("score") or 0.0)
        bias = n.get("regime_bias") or "NEUTRAL"
        buckets[bias] = buckets.get(bias, 0.0) + s
        if s > dom_score:
            dom_score = s
            dom_key = key
    # Pick the bucket with the highest aggregated score.
    label, total = max(buckets.items(), key=lambda kv: kv[1])
    grand_total = sum(buckets.values()) or 1.0
    confidence = round(total / grand_total, 4) if grand_total > 0 else 0.0
    # If the winner is NEUTRAL or score is microscopic, downgrade.
    if total < 0.20:
        return ("NEUTRAL", confidence, dom_key)
    return (label, confidence, dom_key)


# ─── Core ───────────────────────────────────────────────────────────

def extract_narratives(
    catalysts: Optional[List[Dict[str, Any]]],
    signals: Optional[Dict[str, Any]] = None,
    extra_headlines: Optional[List[Dict[str, Any]]] = None,
    prior_state: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute the narrative tracker payload from current-cycle inputs.

    Pure function: produces the new state dict but does NOT write it.
    `prior_state` supplies persistence + acceleration; pass {} for first run.
    """
    n_now = now or _now()
    headlines = _gather_headlines(catalysts, signals, extra_headlines)
    if not isinstance(prior_state, dict):
        prior_state = {}

    # Walk each headline once, attribute to every narrative whose phrase appears.
    narrative_hits: Dict[str, Dict[str, Any]] = {}
    for rule in NARRATIVE_RULES:
        narrative_hits[rule["key"]] = {
            "label":        rule["label"],
            "regime_bias":  rule.get("regime_bias", "NEUTRAL"),
            "sectors_into": list(rule.get("sectors_into") or []),
            "sectors_out":  list(rule.get("sectors_out") or []),
            "phrases":      [],     # phrase-substrings matched THIS cycle
            "articles":     [],     # sample matched articles
        }

    for row in headlines:
        title_lc = _normalize(row.get("title"))
        if not title_lc:
            continue
        for rule in NARRATIVE_RULES:
            key = rule["key"]
            for phrase in (rule.get("phrases") or []):
                if phrase and phrase in title_lc:
                    bucket = narrative_hits[key]
                    if phrase not in bucket["phrases"]:
                        bucket["phrases"].append(phrase)
                    if len(bucket["articles"]) < MAX_ARTICLE_SAMPLES:
                        bucket["articles"].append({
                            "ticker": row.get("ticker") or "",
                            "title":  (row.get("title") or "")[:180],
                            "source": row.get("source") or "",
                        })
                    break  # 1 narrative per (rule, headline) match — no double-count

    # Pull persistence / acceleration from prior_state.
    prior_narratives = (prior_state.get("narratives") or {}) if prior_state else {}

    scored: Dict[str, Dict[str, Any]] = {}
    for rule in NARRATIVE_RULES:
        key = rule["key"]
        bucket = narrative_hits[key]
        frequency = len(bucket["phrases"]) + len(bucket["articles"]) // 4
        prior = prior_narratives.get(key) or {}
        prior_freq = int(prior.get("frequency") or 0)
        prior_persist = int(prior.get("persistence") or 0)
        # Persistence: did we hit this cycle? if yes increment, else decay by 1.
        if frequency > 0:
            persistence = min(MAX_HISTORY, prior_persist + 1)
        else:
            persistence = max(0, prior_persist - 1)
        # Acceleration: relative change in frequency.
        accel = 0.0
        if prior_freq > 0:
            accel = (frequency - prior_freq) / float(max(1, prior_freq))
        elif frequency > 0:
            accel = 1.0  # fresh narrative this cycle
        accel = max(-1.0, min(1.0, accel))
        score = _score_narrative(frequency, persistence, accel)

        # Trim samples
        bucket["phrases"]  = bucket["phrases"][:MAX_PHRASE_SAMPLES]
        bucket["articles"] = bucket["articles"][:MAX_ARTICLE_SAMPLES]

        scored[key] = {
            "label":         bucket["label"],
            "regime_bias":   bucket["regime_bias"],
            "sectors_into":  bucket["sectors_into"],
            "sectors_out":   bucket["sectors_out"],
            "frequency":     int(frequency),
            "persistence":   int(persistence),
            "acceleration":  round(accel, 4),
            "score":         score,
            "phrases":       bucket["phrases"],
            "matched_articles": bucket["articles"],
        }

    # Sector pressure rollup: sum scaled scores across narratives' sector tags.
    pressure: Dict[str, float] = {s: 0.0 for s in _BASE_SECTORS}
    for key, n in scored.items():
        s = float(n.get("score") or 0.0)
        if s <= 0.0:
            continue
        for sec in (n.get("sectors_into") or []):
            pressure[sec] = pressure.get(sec, 0.0) + s
        for sec in (n.get("sectors_out") or []):
            pressure[sec] = pressure.get(sec, 0.0) - s

    # Clamp pressure to [-1, +1] for downstream consumption.
    for sec, v in list(pressure.items()):
        pressure[sec] = round(max(-1.0, min(1.0, v)), 4)

    regime_shift, confidence, dominant_key = _classify_regime_shift(scored)

    # Update rolling history (capped).
    history = list(prior_state.get("history") or [])
    history.append({
        "cycle_ts": n_now.isoformat(),
        "dominant_narrative": dominant_key,
        "regime_shift":       regime_shift,
        "score":              float(scored.get(dominant_key, {}).get("score", 0.0))
                              if dominant_key else 0.0,
    })
    history = history[-MAX_HISTORY:]

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "cycles_observed":          len(history),
        "dominant_narrative":       dominant_key,
        "regime_shift":             regime_shift,
        "regime_shift_confidence":  confidence,
        "narratives":               scored,
        "sector_pressure":          pressure,
        "history":                  history,
        "headline_count":           len(headlines),
    }
    return payload


def write_narrative_tracker(
    data_dir: Path,
    catalysts: Optional[List[Dict[str, Any]]] = None,
    signals: Optional[Dict[str, Any]] = None,
    extra_headlines: Optional[List[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute + persist docs/data/narrative_tracker.json. Idempotent."""
    prior = _load_json(data_dir / FILENAME) or {}
    payload = extract_narratives(
        catalysts=catalysts, signals=signals,
        extra_headlines=extra_headlines,
        prior_state=prior, now=now,
    )
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[narrative_tracker] write failed: {e}")
    return payload


def load_narrative_tracker(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {
        "version": VERSION,
        "narratives": {},
        "sector_pressure": {},
        "dominant_narrative": "",
        "regime_shift": "NEUTRAL",
        "regime_shift_confidence": 0.0,
        "history": [],
    }


def sector_pressure_for_ticker(
    narrative: Dict[str, Any],
    ticker_sector: Optional[str],
) -> float:
    """Convenience for downstream code: return the rolled-up pressure for the
    sector a ticker belongs to. 0.0 if unknown/missing."""
    if not ticker_sector:
        return 0.0
    sp = (narrative or {}).get("sector_pressure") or {}
    try:
        return float(sp.get(ticker_sector, 0.0) or 0.0)
    except Exception:
        return 0.0


__all__ = [
    "VERSION",
    "NARRATIVE_RULES",
    "extract_narratives",
    "write_narrative_tracker",
    "load_narrative_tracker",
    "sector_pressure_for_ticker",
]
