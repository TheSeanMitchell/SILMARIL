"""silmaril.portfolios.capital_efficiency — Alpha 5.1 active-competition engine.

What it does
────────────
The master directive: "every dollar trapped in sideways names, low
momentum, fading narratives, weak sectors, stalled breakouts IS
opportunity cost."

This engine continuously scores how well each open position's capital
is working RIGHT NOW, vs the best ranked opportunity it could be in.
The output is a per-position `efficiency_score` (0..1) and a clear
`rotation_recommendation` (HOLD / WATCH / ROTATE / FORCE_ROTATE).

Inputs (all already on disk from earlier sidecars):
  - position_health.json     — momentum / vulnerability / rotation_score
  - conviction_ranking.json  — ranked_opportunities + alternative scores
  - narrative_tracker.json   — sector pressure (negative = fading sector)
  - sector_rotation.json     — flow_score per sector
  - execution_policy.json    — deployment_pressure / urgency tickers

A position's efficiency = weighted blend of:
  • momentum_score                 +0.25   (do we still have upward push?)
  • (1 - vulnerability_score)      +0.20   (PAR risk)
  • rotation_score                 +0.20   (holdings_review's own score)
  • sector_flow_score normalized   +0.15
  • (alternative_score gap)        -0.20   (cheaper to be in the alt?)

System-wide rollup:
  - deployment_efficiency_score    (% of capital in positions ≥ 0.60 eff)
  - idle_capital_drag              (idle cash as % of equity)
  - sgov_over_allocation           (SGOV ratio vs deployment_floor.max_sgov_ratio)
  - stale_holding_drag             (% of book in WATCH/FORCE_ROTATE)

Output (docs/data/capital_efficiency.json)
──────────────────────────────────────────
{
  "version": "5.1", "generated_at": "...",
  "positions": [
     {"owner":"LEGACY","ticker":"NVDA","sector":"Technology",
      "efficiency_score":0.72,"recommendation":"HOLD",
      "components":{"momentum":0.62,"safety":0.85,"rotation":0.65,
                     "sector":0.40,"alt_gap":-0.10},
      "alt_ticker":"AMD","alt_score":0.81,
      "rationale":"strong base; AMD only marginally better"},
     ...
  ],
  "summary": {
     "positions":                12,
     "deployment_efficiency_score": 0.73,
     "idle_capital_drag":           0.06,
     "sgov_over_allocation":         0.0,
     "stale_holding_drag":          0.16,
     "rotation_recommendations":  {"HOLD":7,"WATCH":3,"ROTATE":1,"FORCE_ROTATE":1}
  },
  "rationale": "..."
}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


VERSION  = "5.1"
FILENAME = "capital_efficiency.json"

# Recommendation thresholds (deterministic).
THRESH_HOLD          = 0.65
THRESH_WATCH         = 0.45
THRESH_ROTATE        = 0.30
THRESH_FORCE         = 0.15
# Alt-gap thresholds — bigger gap = stronger pressure to swap.
ALT_GAP_WATCH        = 0.10
ALT_GAP_ROTATE       = 0.20

# Component weights — sum chosen to produce ~[-0.25, +0.95] before clamping.
W_MOMENTUM    =  0.25
W_SAFETY      =  0.20
W_ROTATION    =  0.20
W_SECTOR      =  0.15
W_ALT_PENALTY = -0.20

# Bounded conviction-multiplier mapping: efficiency 0..1 → 0.85..1.05.
# A position with efficiency=1.0 gets a +5% conviction lift; efficiency=0.0
# subtracts 15%. This is intentionally smaller than setup_lift to avoid
# triple-counting (setup_lift + sector_lift + capital_efficiency).
CAPEFF_LIFT_MIN = 0.85
CAPEFF_LIFT_MAX = 1.05


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


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _build_alt_score_index(
    conviction_ranking: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Best ranked alternative by sector → {sector: {ticker, score}}."""
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(conviction_ranking, dict):
        return out
    ranked = conviction_ranking.get("ranked_opportunities") or []
    # Group by sector, keep best score per sector (excluding tickers in book
    # — caller passes those out via the `exclude_set` arg of compute_efficiency).
    by_sec: Dict[str, List[Dict[str, Any]]] = {}
    for r in ranked:
        if not isinstance(r, dict):
            continue
        sec = r.get("sector") or r.get("asset_class") or "Unknown"
        by_sec.setdefault(sec, []).append(r)
    for sec, lst in by_sec.items():
        lst.sort(key=lambda d: _safe_f(d.get("score")), reverse=True)
        out[sec] = lst[:5]  # top 5 alternatives per sector
    return out


def _best_alt_for(
    ticker_in_position: str,
    sector: Optional[str],
    alt_index: Dict[str, List[Dict[str, Any]]],
    exclude_set: set,
) -> Optional[Dict[str, Any]]:
    """Pick the best ranked opportunity in the same sector that we don't
    already hold."""
    if not sector:
        return None
    candidates = alt_index.get(sector) or []
    for cand in candidates:
        t = (cand.get("ticker") or "").upper()
        if not t or t == ticker_in_position.upper() or t in exclude_set:
            continue
        return cand
    return None


def compute_position_efficiency(
    ph_row: Dict[str, Any],
    alt_index: Dict[str, List[Dict[str, Any]]],
    exclude_set: set,
    sector_flow: Dict[str, float],
) -> Dict[str, Any]:
    """Score one open position's capital efficiency.

    ph_row is a row from position_health.json.
    """
    momentum = _safe_f(ph_row.get("momentum_score"))
    vuln     = _safe_f(ph_row.get("vulnerability_score"))
    rot_score = _safe_f(ph_row.get("rotation_score"))
    sector    = ph_row.get("sector")
    ticker    = (ph_row.get("ticker") or "").upper()
    flow_raw  = _safe_f(sector_flow.get(sector or "", 0.0))
    # Normalise sector flow -1..+1 → 0..1
    sector_n  = (flow_raw + 1.0) / 2.0

    alt = _best_alt_for(ticker, sector, alt_index, exclude_set)
    alt_score = _safe_f((alt or {}).get("score"))
    alt_ticker = (alt or {}).get("ticker")
    # alt_gap > 0 means the alternative is better than our holding.
    # We compare to rotation_score because both come from holdings_review/conviction
    # scoring on the same 0..1 scale.
    alt_gap = max(0.0, alt_score - rot_score) if alt_score > 0 else 0.0

    safety = 1.0 - vuln
    eff = (
        W_MOMENTUM    * momentum
        + W_SAFETY    * safety
        + W_ROTATION  * rot_score
        + W_SECTOR    * sector_n
        + W_ALT_PENALTY * min(0.5, alt_gap)   # cap the penalty
    )
    eff = _clamp(eff, 0.0, 1.0)

    # Convert to bounded conviction-multiplier (lift) for downstream use.
    lift = CAPEFF_LIFT_MIN + eff * (CAPEFF_LIFT_MAX - CAPEFF_LIFT_MIN)
    lift = round(_clamp(lift, CAPEFF_LIFT_MIN, CAPEFF_LIFT_MAX), 4)

    # Recommendation
    if ph_row.get("force_rotation") or ph_row.get("status") == "FORCE_ROTATE":
        rec = "FORCE_ROTATE"
    elif eff <= THRESH_FORCE:
        rec = "FORCE_ROTATE"
    elif eff <= THRESH_ROTATE or alt_gap >= ALT_GAP_ROTATE:
        rec = "ROTATE"
    elif eff <= THRESH_WATCH or alt_gap >= ALT_GAP_WATCH:
        rec = "WATCH"
    else:
        rec = "HOLD"

    bits: List[str] = []
    if momentum < 0.35:
        bits.append(f"momentum {momentum:.2f}")
    if vuln >= 0.45:
        bits.append(f"vuln {vuln:.2f}")
    if flow_raw <= -0.20:
        bits.append(f"sector flow {flow_raw:+.2f}")
    if alt_gap >= 0.10:
        bits.append(f"alt {alt_ticker} +{alt_gap:.2f}")
    if not bits:
        bits.append("steady")
    rationale = " · ".join(bits)

    return {
        "owner":             ph_row.get("owner"),
        "ticker":            ticker,
        "sector":            sector,
        "efficiency_score":  round(eff, 4),
        "lift":              lift,
        "recommendation":    rec,
        "components":        {
            "momentum": round(momentum, 4),
            "safety":   round(safety, 4),
            "rotation": round(rot_score, 4),
            "sector":   round(sector_n, 4),
            "alt_gap":  round(-min(0.5, alt_gap), 4),  # signed component
        },
        "alt_ticker":        alt_ticker,
        "alt_score":         round(alt_score, 4) if alt_score > 0 else None,
        "rationale":         rationale,
    }


def build_capital_efficiency(
    data_dir: Path,
    multi_account_results: Optional[Dict[str, Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute + persist capital-efficiency rollup."""
    n_now = now or datetime.now(timezone.utc)

    position_health    = _load_json(data_dir / "position_health.json") or {}
    conviction_ranking = _load_json(data_dir / "conviction_ranking.json") or {}
    sector_rotation    = _load_json(data_dir / "sector_rotation.json") or {}
    deployment_floor   = _load_json(data_dir / "deployment_floor.json") or {}

    sector_flow: Dict[str, float] = {}
    for sec, info in (sector_rotation.get("sectors") or {}).items():
        sector_flow[sec] = _safe_f((info or {}).get("flow_score"))

    rows = position_health.get("rows") or []
    held_set = {(r.get("ticker") or "").upper() for r in rows if r.get("ticker")}
    alt_index = _build_alt_score_index(conviction_ranking)

    positions_out: List[Dict[str, Any]] = []
    for r in rows:
        positions_out.append(
            compute_position_efficiency(r, alt_index, held_set, sector_flow)
        )

    # System rollup
    n = len(positions_out)
    good = sum(1 for p in positions_out if p["efficiency_score"] >= 0.60)
    watch = sum(1 for p in positions_out if p["recommendation"] == "WATCH")
    rotate = sum(1 for p in positions_out if p["recommendation"] == "ROTATE")
    force = sum(1 for p in positions_out if p["recommendation"] == "FORCE_ROTATE")
    hold  = sum(1 for p in positions_out if p["recommendation"] == "HOLD")

    deployment_eff = round(good / float(n), 4) if n else 0.0

    # Idle drag + SGOV over-alloc from deployment_floor
    contracts = (deployment_floor.get("contracts") or {})
    if contracts:
        idle_pcts = [_safe_f(c.get("cash_ratio")) for c in contracts.values()]
        sgov_over = []
        for c in contracts.values():
            ratio = _safe_f(c.get("sgov_ratio"))
            max_r = _safe_f(c.get("max_sgov_ratio"))
            sgov_over.append(max(0.0, ratio - max_r))
        idle_drag = round(sum(idle_pcts) / len(idle_pcts), 4) if idle_pcts else 0.0
        sgov_over_alloc = round(sum(sgov_over) / len(sgov_over), 4) if sgov_over else 0.0
    else:
        idle_drag = 0.0
        sgov_over_alloc = 0.0
    stale_drag = round((watch + rotate + force) / float(n), 4) if n else 0.0

    summary = {
        "positions":                    n,
        "deployment_efficiency_score":  deployment_eff,
        "idle_capital_drag":            idle_drag,
        "sgov_over_allocation":         sgov_over_alloc,
        "stale_holding_drag":           stale_drag,
        "rotation_recommendations":     {
            "HOLD":          hold,
            "WATCH":         watch,
            "ROTATE":        rotate,
            "FORCE_ROTATE":  force,
        },
    }

    bits: List[str] = []
    bits.append(f"{good}/{n} efficient" if n else "no open positions")
    if force or rotate:
        bits.append(f"{force + rotate} rotate-now")
    if idle_drag > 0.15:
        bits.append(f"idle drag {idle_drag*100:.0f}%")
    if sgov_over_alloc > 0.05:
        bits.append(f"SGOV over {sgov_over_alloc*100:.0f}%")
    rationale = " · ".join(bits)

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "positions":    positions_out,
        "summary":      summary,
        "rationale":    rationale,
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[capital_efficiency] write failed: {e}")
    return payload


def get_efficiency_lift(
    data_dir: Path,
    ticker: str,
    owner: Optional[str] = None,
) -> float:
    """Lookup the per-position lift. 1.0 when ticker not held / file missing."""
    if not ticker:
        return 1.0
    body = _load_json(data_dir / FILENAME)
    if not isinstance(body, dict):
        return 1.0
    for p in (body.get("positions") or []):
        if (p.get("ticker") or "").upper() != ticker.upper():
            continue
        if owner and p.get("owner") and owner != p.get("owner"):
            continue
        v = _safe_f(p.get("lift"), 1.0)
        return _clamp(v, CAPEFF_LIFT_MIN, CAPEFF_LIFT_MAX)
    return 1.0


def load_capital_efficiency(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "positions": [],
             "summary": {"positions": 0, "deployment_efficiency_score": 0.0,
                          "idle_capital_drag": 0.0, "sgov_over_allocation": 0.0,
                          "stale_holding_drag": 0.0,
                          "rotation_recommendations": {}}}


__all__ = [
    "VERSION", "CAPEFF_LIFT_MIN", "CAPEFF_LIFT_MAX",
    "compute_position_efficiency", "build_capital_efficiency",
    "get_efficiency_lift", "load_capital_efficiency",
]
