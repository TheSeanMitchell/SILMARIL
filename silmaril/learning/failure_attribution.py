"""silmaril.learning.failure_attribution — Alpha 5.1 failure attribution.

What it does
────────────
The master directive: "the system must stop merely logging losses; it
must classify WHY losses occurred." Without failure attribution,
learning remains shallow.

Every closed losing trade is classified into ONE primary failure
category (and optionally up to two secondary categories) so the
operator can SEE the recurring mistakes and the conviction engine
can adjust the parameters that drive them.

Categories (master directive):
  - entered_too_late
  - weak_catalyst
  - low_volume_confirmation
  - narrative_exhaustion
  - sector_deterioration
  - broad_market_reversal
  - overextended_breakout
  - poor_deployment_timing
  - excessive_defensive_liquidation
  - stale_capital_retention
  - weak_rotation_timing
  - premature_harvesting
  - under_sized_winner          (positive net; sized too small to matter)
  - over_sized_loser             (negative net; sized too big)

The classifier is purely rule-based, reading whatever fields are present
on the alpaca_attribution row plus contemporaneous narrative_tracker /
sector_rotation / market_state state at close time (if attributable).

Output (docs/data/failure_attribution.json)
───────────────────────────────────────────
{
  "version": "5.1", "generated_at": "...",
  "rows": [
     {"ticker":"AAPL","pnl":-72.50,"primary":"narrative_exhaustion",
      "secondary":["sector_deterioration"],
      "rationale":"closed on 6th cycle of fading AI narrative; sector flow -0.40"},
     ...
  ],
  "summary": {
     "samples_classified": 32,
     "by_category": {
        "narrative_exhaustion":   8,
        "sector_deterioration":   6,
        "entered_too_late":       4,
        ...
     },
     "by_account": {...},
     "by_sector":  {...},
     "top_failures": [
        {"category":"narrative_exhaustion","count":8,"avg_loss":-1.42},
        ...
     ]
  }
}
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION  = "5.1"
FILENAME = "failure_attribution.json"

CATEGORIES = [
    "entered_too_late",
    "weak_catalyst",
    "low_volume_confirmation",
    "narrative_exhaustion",
    "sector_deterioration",
    "broad_market_reversal",
    "overextended_breakout",
    "poor_deployment_timing",
    "excessive_defensive_liquidation",
    "stale_capital_retention",
    "weak_rotation_timing",
    "premature_harvesting",
    "under_sized_winner",
    "over_sized_loser",
]

# Threshold tuning constants
LATE_ENTRY_5D_GAIN_PCT  = 0.10
OVEREXT_BREAKOUT_5D_PCT  = 0.15
WEAK_CATALYST_LABELS = {"weak", "stale", "vague", "weak_buy", "vague_buy", "no_catalyst"}
PREMATURE_HARVEST_GAIN  = 0.02   # closed for <2% gain but momentum still strong
PREMATURE_HARVEST_HOLD  = 18.0   # within 18h
STALE_RETENTION_HOURS   = 96.0
UNDER_SIZED_PNL         = 25.0   # absolute $ — winner that didn't move the needle
OVER_SIZED_LOSS         = 150.0  # absolute $ — loser that took a big chunk


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


def _classify_one(
    trade: Dict[str, Any],
    narrative: Dict[str, Any],
    sector_rotation: Dict[str, Any],
) -> Tuple[str, List[str], str]:
    """Return (primary, secondary_list, rationale)."""
    pnl = _safe_f(trade.get("pnl") or trade.get("realized_pnl") or trade.get("net_pnl"))
    pct = _safe_f(trade.get("realized_pnl_pct") or trade.get("pnl_pct"))
    hold = _safe_f(trade.get("hold_hours") or (trade.get("hold_days") or 0) * 24)
    sector = trade.get("sector") or "Unknown"
    catalyst_label = (trade.get("catalyst_label") or "").lower()
    entry_5d_gain = _safe_f(trade.get("entry_five_day_return"))
    close_reason = (trade.get("close_reason") or trade.get("exit_reason") or "").lower()
    momentum_at_close = _safe_f(trade.get("momentum_at_close"))
    market_mode_at_close = (trade.get("market_mode_at_close") or "").upper()

    # Per-sector narrative & flow at close
    sector_flow = _safe_f(((sector_rotation or {}).get("sectors") or {})
                              .get(sector, {}).get("flow_score"))
    regime_shift = (narrative or {}).get("regime_shift", "NEUTRAL")

    primary = "unspecified"
    secondary: List[str] = []
    bits: List[str] = []

    # Net winner that was tiny → under_sized_winner.
    if pnl > 0 and abs(pnl) < UNDER_SIZED_PNL:
        primary = "under_sized_winner"
        bits.append(f"net +${pnl:.2f} too small to matter")

    # Net huge loss → over_sized_loser is the primary classification
    elif pnl < 0 and abs(pnl) >= OVER_SIZED_LOSS:
        primary = "over_sized_loser"
        bits.append(f"net ${pnl:.2f} — sized too aggressively")

    # Losers: classify by why we lost
    elif pnl < 0:
        # Entered too late
        if entry_5d_gain >= LATE_ENTRY_5D_GAIN_PCT:
            primary = "entered_too_late"
            bits.append(f"entered after +{entry_5d_gain*100:.1f}% 5d run")
        # Overextended breakout
        elif entry_5d_gain >= OVEREXT_BREAKOUT_5D_PCT:
            primary = "overextended_breakout"
            bits.append(f"entered into +{entry_5d_gain*100:.1f}% extension")
        # Sector deteriorated
        elif sector_flow <= -0.25:
            primary = "sector_deterioration"
            bits.append(f"{sector} flow {sector_flow:+.2f} during hold")
        # Narrative collapsed
        elif regime_shift == "RISK_OFF":
            primary = "broad_market_reversal"
            bits.append("regime flipped RISK_OFF during hold")
        # Weak / vague catalyst label
        elif catalyst_label in WEAK_CATALYST_LABELS:
            primary = "weak_catalyst"
            bits.append(f"catalyst label '{catalyst_label or 'none'}'")
        # Narrative exhaustion (long hold with no progress)
        elif hold >= STALE_RETENTION_HOURS and pct <= 0.0:
            primary = "narrative_exhaustion"
            bits.append(f"held {hold:.0f}h with no net progress")
        # Stale capital retention (held a stagnant position too long)
        elif hold >= STALE_RETENTION_HOURS:
            primary = "stale_capital_retention"
            bits.append(f"held {hold:.0f}h with stagnant return")
        # Excessive defensive liquidation: market_mode=DEFENSIVE/PRESERVATION
        elif market_mode_at_close in ("DEFENSIVE", "PRESERVATION") and pct > -0.01:
            primary = "excessive_defensive_liquidation"
            bits.append(f"closed during {market_mode_at_close} at only {pct*100:.2f}%")
        # Weak rotation timing — closed at the very bottom of a sector flow trough
        elif sector_flow <= -0.10 and "rotation" in close_reason:
            primary = "weak_rotation_timing"
            bits.append(f"rotated out at sector trough {sector_flow:+.2f}")
        # Poor deployment timing — closed quickly on a regime mismatch
        elif hold < 12 and market_mode_at_close in ("DEFENSIVE", "PRESERVATION"):
            primary = "poor_deployment_timing"
            bits.append(f"opened then closed in {hold:.0f}h ({market_mode_at_close})")
        else:
            # Last-resort generic loser
            primary = "weak_catalyst"
            bits.append("loss without clear primary cause; defaulted weak_catalyst")

        # Secondary tags (additive, max 2)
        if primary != "low_volume_confirmation":
            if _safe_f(trade.get("volume_z_score_at_entry")) < -0.5:
                secondary.append("low_volume_confirmation")
        if primary != "narrative_exhaustion" and momentum_at_close <= 0.30:
            secondary.append("narrative_exhaustion")
        secondary = secondary[:2]

    # Premature harvest — closed early in profit but momentum was good
    if pnl > 0 and primary == "unspecified" and \
       0 < pct < PREMATURE_HARVEST_GAIN and hold < PREMATURE_HARVEST_HOLD and \
       momentum_at_close >= 0.55:
        primary = "premature_harvesting"
        bits.append(f"closed +{pct*100:.2f}% in {hold:.0f}h; momentum {momentum_at_close:.2f}")

    if primary == "unspecified":
        # Wins not in any failure bucket → uncategorized
        primary = "no_failure"
        bits.append(f"net ${pnl:+.2f}; healthy outcome")

    rationale = "; ".join(bits)
    return primary, secondary, rationale


def build_failure_attribution(
    data_dir: Path,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Walk attribution + classify every closed trade."""
    n_now = now or datetime.now(timezone.utc)
    attrib = _load_json(data_dir / "alpaca_attribution.json")
    narrative = _load_json(data_dir / "narrative_tracker.json") or {}
    sector_rotation = _load_json(data_dir / "sector_rotation.json") or {}

    rows_in = []
    if isinstance(attrib, dict):
        rows_in = attrib.get("orders") or attrib.get("rows") or []

    rows_out: List[Dict[str, Any]] = []
    by_cat: Dict[str, int] = defaultdict(int)
    by_cat_pnl: Dict[str, List[float]] = defaultdict(list)
    by_account: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_sector:  Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for t in rows_in:
        if not isinstance(t, dict):
            continue
        pnl = _safe_f(t.get("pnl") or t.get("realized_pnl") or t.get("net_pnl"))
        # Only classify rows that have an actual close
        if pnl == 0 and not t.get("realized_pnl_pct"):
            continue
        primary, secondary, rationale = _classify_one(t, narrative, sector_rotation)
        rows_out.append({
            "ticker":    (t.get("ticker") or "").upper(),
            "account":   t.get("account_id"),
            "sector":    t.get("sector") or "Unknown",
            "pnl":       round(pnl, 2),
            "pnl_pct":   _safe_f(t.get("realized_pnl_pct") or t.get("pnl_pct")),
            "primary":   primary,
            "secondary": secondary,
            "rationale": rationale,
        })
        if primary in CATEGORIES:
            by_cat[primary] += 1
            by_cat_pnl[primary].append(pnl)
        if t.get("account_id"):
            by_account[t["account_id"]][primary] += 1
        by_sector[t.get("sector") or "Unknown"][primary] += 1

    top_failures: List[Dict[str, Any]] = []
    for cat, count in by_cat.items():
        pnls = by_cat_pnl.get(cat, [])
        avg = round(sum(pnls) / len(pnls), 4) if pnls else 0.0
        top_failures.append({
            "category":   cat,
            "count":      count,
            "total_pnl":  round(sum(pnls), 2),
            "avg_loss":   avg,
        })
    top_failures.sort(key=lambda d: (d["total_pnl"], -d["count"]))

    summary = {
        "samples_classified":  len(rows_out),
        "by_category":         dict(by_cat),
        "by_account":          {k: dict(v) for k, v in by_account.items()},
        "by_sector":           {k: dict(v) for k, v in by_sector.items()},
        "top_failures":        top_failures[:6],
    }

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "rows":         rows_out,
        "summary":      summary,
        "categories":   CATEGORIES,
        "rationale":    (f"{len(rows_out)} trades classified · "
                            f"{sum(1 for r in rows_out if r['primary'] not in ('no_failure',))} "
                            "failure-tagged"),
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[failure_attribution] write failed: {e}")
    return payload


def load_failure_attribution(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "rows": [],
             "summary": {"samples_classified": 0, "by_category": {},
                          "by_account": {}, "by_sector": {}, "top_failures": []},
             "categories": CATEGORIES,
             "rationale": "no failure_attribution file"}


__all__ = [
    "VERSION", "CATEGORIES",
    "build_failure_attribution", "load_failure_attribution",
]
