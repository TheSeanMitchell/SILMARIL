"""silmaril.portfolios.staleness — Position-pruning advisory engine.

What it does
────────────
For every open position (per agent AND for each Alpaca account), compute
a "staleness scorecard" and emit a HOLD / TRIM / EXIT recommendation.

For Alpha 3.0 this is **advisory only** — recommendations are written to
docs/data/position_advisory.json and rendered on the dashboard. The
existing momentum_exit.py logic still does the actual closing. This lets
us calibrate the aggression knob safely before flipping it to auto.

Per-agent learnable aggression (pokemon-style)
──────────────────────────────────────────────
Each agent carries a `staleness_aggression` parameter in [0.0, 1.0]:

  0.0 → ultra-patient. Only the absolute worst stale positions get EXIT.
  0.5 → balanced (the default).
  1.0 → twitchy. Almost anything that isn't moving gets TRIMmed or EXITed.

The Senate breeding cycle can mutate this parameter on every generation.
For now it's read from docs/data/agent_staleness_params.json (initialized
to 0.5 for every agent on first run); the Senate election process can
adjust it in subsequent runs without touching this module.

Inputs
──────
A list of position dicts with at least:
  ticker, entry_price, current_price, peak_price (optional), entry_date,
  qty, asset_class (optional), price_snapshots (optional).

Plus the owning agent's codename so we can look up its aggression knob.

Outputs
───────
docs/data/position_advisory.json — list of:
  {
    "owner": "AEGIS" | "LEGACY" | "HARVEST_3" | ...,
    "ticker": "DIS",
    "recommendation": "HOLD" | "TRIM" | "EXIT",
    "score": 0.42,            # 0=fresh+strong, 1=stale+dying
    "rationale": "Held 3d, intraday flat, 24h move <0.5%",
    "components": { ... },    # individual signal contributions
    "advisory_only": true,
  }
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─── Per-agent aggression knob (the pokemon-style learnable parameter) ──

_DEFAULT_AGGRESSION = 0.5

_AGGRESSION_FILE = "agent_staleness_params.json"


def load_aggression_params(data_dir: Path) -> Dict[str, float]:
    """Load per-agent staleness_aggression values. Missing → default."""
    path = data_dir / _AGGRESSION_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
        return {k: float(v) for k, v in raw.get("params", {}).items()}
    except Exception:
        return {}


def save_aggression_params(data_dir: Path, params: Dict[str, float]) -> None:
    """Persist aggression knobs. Senate breeder writes here too."""
    path = data_dir / _AGGRESSION_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "params": {k: round(float(v), 4) for k, v in params.items()},
        "default": _DEFAULT_AGGRESSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "note": ("Staleness aggression in [0,1]. Lower=more patient, "
                 "higher=twitchier. Mutated by Senate breeder."),
    }, indent=2))


def ensure_aggression_for(data_dir: Path, agents: List[str]) -> Dict[str, float]:
    """Initialize default aggression for any agent missing one. Returns full map."""
    params = load_aggression_params(data_dir)
    changed = False
    for a in agents:
        if a not in params:
            params[a] = _DEFAULT_AGGRESSION
            changed = True
    if changed:
        save_aggression_params(data_dir, params)
    return params


# ─── Scorecard math ─────────────────────────────────────────────────────

@dataclass
class StalenessScore:
    hold_age_days:      float = 0.0
    intraday_drift_pct: float = 0.0   # current vs entry as a fraction
    peak_drop_pct:      float = 0.0   # current vs peak as a fraction (negative when below peak)
    snapshot_volatility:float = 0.0   # stddev of price_snapshots / mean, if available
    momentum_decay:     float = 0.0   # 1 = decaying, 0 = accelerating
    score:              float = 0.0   # composite 0..1
    recommendation:     str   = "HOLD"
    rationale:          str   = ""
    components:         Dict[str, float] = field(default_factory=dict)


def _safe(v, default=0.0):
    try:
        f = float(v)
        if f != f:  # NaN
            return default
        return f
    except Exception:
        return default


def _parse_entry_date(s: Optional[str]) -> Optional[date]:
    if not s: return None
    try:
        return date.fromisoformat(str(s).split("T", 1)[0])
    except Exception:
        return None


def _snapshot_stats(snaps: List[float]) -> tuple:
    """(volatility_norm, momentum_decay) from a small list of recent prices."""
    if not snaps or len(snaps) < 3:
        return 0.0, 0.5  # neutral
    mean = sum(snaps) / len(snaps)
    if mean <= 0:
        return 0.0, 0.5
    # Crude vol: max-min over mean (clipped 0..0.2 → normalized to 0..1)
    spread = (max(snaps) - min(snaps)) / mean
    vol_norm = min(1.0, spread / 0.10)  # 10% range maps to 1.0

    # Momentum decay: is the LATER half flatter than the earlier half?
    half = len(snaps) // 2
    if half < 2:
        return vol_norm, 0.5
    early = snaps[:half]
    late = snaps[-half:]
    early_range = (max(early) - min(early)) / mean
    late_range = (max(late) - min(late)) / mean
    if early_range < 1e-6:
        return vol_norm, 0.5
    # If late_range < early_range → decay (closer to 1.0)
    ratio = late_range / early_range
    decay = max(0.0, min(1.0, 1.0 - ratio))
    return vol_norm, decay


def score_position(
    position: Dict[str, Any],
    today_iso: Optional[str] = None,
) -> StalenessScore:
    """Score a single open position. Returns a StalenessScore.

    This function does NOT apply the aggression knob — it's a pure
    measurement. The recommendation comes from compose_recommendation().

    *** IMPORTANT INVARIANT (Alpha 3.0) ***
    Position hold-age is ALWAYS computed in real calendar days — never
    in market-trading days, never in crypto-continuous hours. The
    `time_basis` helper exists to label agent-age pills on the dashboard
    where market-vs-crypto comparison matters; that helper MUST NOT be
    routed into this scorer. A position that has been sitting unmoved
    from Friday through Tuesday is 4 calendar days stale regardless of
    how you choose to count the market days between them — that real
    elapsed time is what creates opportunity cost on locked-up capital.
    Do not "fix" this to use market_trading_days. It is intentional.
    """
    s = StalenessScore()
    today = _parse_entry_date(today_iso) or datetime.now(timezone.utc).date()
    entry_date = _parse_entry_date(position.get("entry_date") or
                                   position.get("first_seen"))
    if entry_date:
        # Real calendar-day age. Do not import from time_basis.
        s.hold_age_days = float(max(0, (today - entry_date).days))

    entry_price = _safe(position.get("entry_price"))
    current = _safe(position.get("current_price") or position.get("price"))
    peak = _safe(position.get("peak_price")) or max(entry_price, current)

    if entry_price > 0 and current > 0:
        s.intraday_drift_pct = (current - entry_price) / entry_price
    if peak > 0 and current > 0:
        s.peak_drop_pct = (current - peak) / peak  # negative when below peak

    snaps = position.get("price_snapshots") or []
    if isinstance(snaps, list) and len(snaps) >= 3:
        vol, decay = _snapshot_stats([_safe(x) for x in snaps if _safe(x) > 0])
        s.snapshot_volatility = vol
        s.momentum_decay = decay
    else:
        s.snapshot_volatility = 0.0
        s.momentum_decay = 0.5

    # Composite stale-score components (each contributes 0..1)
    age_component = min(1.0, s.hold_age_days / 7.0)               # 7d → 1.0
    drift_flat = 1.0 - min(1.0, abs(s.intraday_drift_pct) / 0.10)  # <10% off entry → flat
    peak_giveback = min(1.0, max(0.0, -s.peak_drop_pct) / 0.05)   # 5% off peak → 1.0
    decay_component = s.momentum_decay                            # 0..1
    illiquidity = 1.0 - s.snapshot_volatility                     # 0 → totally illiquid

    # Weighted composite (must sum to ~1.0 weight)
    composite = (
        0.30 * age_component +
        0.25 * drift_flat +
        0.25 * peak_giveback +
        0.15 * decay_component +
        0.05 * illiquidity
    )
    s.score = round(composite, 4)
    s.components = {
        "age": round(age_component, 4),
        "drift_flat": round(drift_flat, 4),
        "peak_giveback": round(peak_giveback, 4),
        "decay": round(decay_component, 4),
        "illiquidity": round(illiquidity, 4),
    }
    return s


def compose_recommendation(s: StalenessScore, aggression: float) -> StalenessScore:
    """Translate a raw score into HOLD/TRIM/EXIT using the agent's
    aggression knob. Pure function — doesn't mutate the input.

    Thresholds shift with aggression:
      aggression 0.0  → trim @ 0.85, exit @ 0.95  (very patient)
      aggression 0.5  → trim @ 0.65, exit @ 0.80  (balanced default)
      aggression 1.0  → trim @ 0.45, exit @ 0.65  (twitchy)
    """
    a = max(0.0, min(1.0, float(aggression)))
    trim_threshold = 0.85 - 0.40 * a
    exit_threshold = 0.95 - 0.30 * a

    if s.score >= exit_threshold:
        s.recommendation = "EXIT"
    elif s.score >= trim_threshold:
        s.recommendation = "TRIM"
    else:
        s.recommendation = "HOLD"

    # Human-readable rationale
    parts = []
    if s.hold_age_days >= 5:
        parts.append(f"held {s.hold_age_days:.0f}d")
    if abs(s.intraday_drift_pct) < 0.005:
        parts.append("flat from entry")
    elif s.intraday_drift_pct < -0.02:
        parts.append(f"{s.intraday_drift_pct*100:.1f}% underwater")
    elif s.intraday_drift_pct > 0.02:
        parts.append(f"+{s.intraday_drift_pct*100:.1f}% from entry")
    if s.peak_drop_pct < -0.03:
        parts.append(f"{s.peak_drop_pct*100:.1f}% off peak")
    if s.momentum_decay > 0.6:
        parts.append("momentum decaying")
    if not parts:
        parts.append("position stable")
    s.rationale = ", ".join(parts) + f" · score {s.score:.2f} @ aggression {a:.2f}"
    return s


# ─── Advisory writer ────────────────────────────────────────────────────

def write_advisory(
    data_dir: Path,
    positions_by_owner: Dict[str, List[Dict[str, Any]]],
    aggression_params: Dict[str, float],
    today_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Build position_advisory.json from all open positions across owners.

    `positions_by_owner` maps each owner ("AEGIS", "LEGACY", "HARVEST_3", ...)
    to its list of open position dicts. Aggregation is downstream's problem.
    """
    advisories: List[Dict[str, Any]] = []
    for owner, positions in positions_by_owner.items():
        agg = aggression_params.get(owner, _DEFAULT_AGGRESSION)
        for p in positions or []:
            ticker = p.get("ticker") or p.get("symbol")
            if not ticker:
                continue
            s = score_position(p, today_iso=today_iso)
            s = compose_recommendation(s, agg)
            advisories.append({
                "owner": owner,
                "ticker": ticker,
                "recommendation": s.recommendation,
                "score": s.score,
                "rationale": s.rationale,
                "components": s.components,
                "aggression": round(agg, 4),
                "hold_age_days": s.hold_age_days,
                "intraday_drift_pct": round(s.intraday_drift_pct, 4),
                "peak_drop_pct": round(s.peak_drop_pct, 4),
                "advisory_only": True,
            })

    # Sort: highest score first (most stale at top)
    advisories.sort(key=lambda r: -r["score"])

    summary = {
        "total": len(advisories),
        "hold": sum(1 for a in advisories if a["recommendation"] == "HOLD"),
        "trim": sum(1 for a in advisories if a["recommendation"] == "TRIM"),
        "exit": sum(1 for a in advisories if a["recommendation"] == "EXIT"),
    }
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "advisory_only": True,
        "note": ("Advisory only — recommendations are NOT auto-executed in "
                 "Alpha 3.0. Existing trailing-stop / momentum-exit logic "
                 "still does the actual closing."),
        "summary": summary,
        "by_owner": {},
        "advisories": advisories,
    }
    for a in advisories:
        out["by_owner"].setdefault(a["owner"], []).append({
            "ticker": a["ticker"],
            "recommendation": a["recommendation"],
            "score": a["score"],
            "rationale": a["rationale"],
        })

    path = data_dir / "position_advisory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str))
    return out


__all__ = [
    "StalenessScore",
    "load_aggression_params",
    "save_aggression_params",
    "ensure_aggression_for",
    "score_position",
    "compose_recommendation",
    "write_advisory",
]
