"""silmaril.portfolios.orchestrator — Alpha 5.1 portfolio-level central brain.

What it does
────────────
The master directive: "the system thinks too much in ticker-level
decisions instead of portfolio-level orchestration." Build a single
engine that owns:

  - total exposure management
  - sector concentration logic
  - correlation balancing
  - offensive vs defensive posture
  - volatility budget
  - deployment pacing
  - capital recycling cadence
  - account role enforcement
  - redeployment prioritization
  - idle capital suppression
  - coordinated rotation

This module READS every existing sidecar (it is a pure synthesizer,
not a competing executor) and emits a coherent portfolio directive:

  - target_market_exposure_pct        (per the regime + risk)
  - max_sector_concentration_pct      (per sector ceiling)
  - max_position_concentration_pct    (per ticker ceiling)
  - volatility_budget_pct             (sum of position ATR / equity)
  - deployment_pacing                 (deploy_fast / deploy_steady / deploy_slow)
  - account_priority_order            (which account gets next $ first)
  - recycling_cadence_hours           (how fast to rotate)
  - posture                           (OFFENSIVE / NEUTRAL / DEFENSIVE)

It also computes a **system_objective_today** — one of:

  - DEPLOY_AGGRESSIVELY    (under-deployed, mode=ATTACK, narrative=risk_on)
  - DEPLOY_SELECTIVELY     (mode=BALANCED, idle > 15%)
  - ROTATE_TO_LEADERS      (force-rotations queued, sector flows clear)
  - HARVEST_AND_HOLD       (above harvest_threshold, no urgent opps)
  - DEFENSE_HARDENING      (risk_off rising, vol up, regime unstable)
  - RECOVER_FROM_DRAWDOWN  (equity < deployment_base AND SGOV holds capital)

Output (docs/data/orchestrator.json)
────────────────────────────────────
{
  "version": "5.1",
  "generated_at": "...",
  "directive": {
     "system_objective_today":         "DEPLOY_AGGRESSIVELY",
     "posture":                        "OFFENSIVE",
     "target_market_exposure_pct":     0.80,
     "max_sector_concentration_pct":   0.35,
     "max_position_concentration_pct": 0.12,
     "volatility_budget_pct":          0.04,
     "deployment_pacing":              "deploy_fast",
     "recycling_cadence_hours":        12,
     "account_priority_order":         ["LEGACY","HARVEST_3","HARVEST_5"]
  },
  "current_state": {
     "system_equity":          30_182.0,
     "system_deployed_ratio":   0.78,
     "system_sgov_ratio":       0.03,
     "system_idle_ratio":       0.19,
     "active_regimes":          ["rotational_bull","energy_expansion"],
     "force_rotations_queued":  1,
     "watch_positions":         3,
     "violation_flags":         []
  },
  "sector_targets": {
     "Technology": {"target_pct":0.22,"current_pct":0.18,"action":"add"},
     "Energy":     {"target_pct":0.18,"current_pct":0.05,"action":"add_urgent"},
     ...
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
FILENAME = "orchestrator.json"

# Posture mapping from market_mode → default exposure target.
POSTURE_DEFAULTS = {
    "ATTACK":       {"posture": "OFFENSIVE", "target_exposure": 0.85, "vol_budget": 0.05,
                     "pacing": "deploy_fast",   "cadence_hours": 8},
    "BALANCED":     {"posture": "NEUTRAL",   "target_exposure": 0.75, "vol_budget": 0.04,
                     "pacing": "deploy_steady", "cadence_hours": 12},
    "DEFENSIVE":    {"posture": "DEFENSIVE", "target_exposure": 0.60, "vol_budget": 0.03,
                     "pacing": "deploy_slow",  "cadence_hours": 24},
    "PRESERVATION": {"posture": "DEFENSIVE", "target_exposure": 0.40, "vol_budget": 0.02,
                     "pacing": "deploy_minimal", "cadence_hours": 48},
}

# Hard caps that never relax.
HARD_MAX_SECTOR_PCT   = 0.40       # 40% in one sector max
HARD_MAX_POSITION_PCT = 0.15       # 15% in one ticker max


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


def _aggregate_holdings_by_sector(
    multi_account_results: Optional[Dict[str, Dict[str, Any]]],
    sector_lookup: Optional[Dict[str, str]],
) -> Dict[str, float]:
    """Sum market value per sector across all enabled accounts."""
    out: Dict[str, float] = {}
    if not isinstance(multi_account_results, dict):
        return out
    for aid, astate in multi_account_results.items():
        if not isinstance(astate, dict) or not astate.get("enabled"):
            continue
        for p in (astate.get("positions_snapshot") or []):
            sym = (p.get("symbol") or p.get("ticker") or "").upper()
            if not sym or sym in ("SGOV", "BIL", "SHY", "TFLO", "USFR"):
                continue
            mv = _safe_f(p.get("market_value")) or (
                  _safe_f(p.get("qty")) * _safe_f(p.get("current_price")))
            if mv <= 0:
                continue
            sec = (sector_lookup or {}).get(sym) or "Unknown"
            out[sec] = out.get(sec, 0.0) + mv
    return out


def _aggregate_system_equity(
    deployment_floor: Optional[Dict[str, Any]],
) -> Dict[str, float]:
    if not isinstance(deployment_floor, dict):
        return {"equity": 0.0, "deployed": 0.0, "sgov": 0.0, "cash": 0.0}
    eq, dep, sgov, cash = 0.0, 0.0, 0.0, 0.0
    for c in (deployment_floor.get("contracts") or {}).values():
        eq   += _safe_f(c.get("live_equity"))
        dep  += _safe_f(c.get("deployed"))
        sgov += _safe_f(c.get("live_sgov"))
        cash += _safe_f(c.get("live_cash"))
    return {"equity": eq, "deployed": dep, "sgov": sgov, "cash": cash}


def _account_priority_order(
    deployment_floor: Optional[Dict[str, Any]],
) -> List[str]:
    """Which account most needs the next deploy dollar?

    Priority = underdeployed first, then biggest cash_ratio, then biggest
    redeploy_from_sgov_amount. Always returns deterministic ordering."""
    if not isinstance(deployment_floor, dict):
        return ["LEGACY", "HARVEST_3", "HARVEST_5"]
    rows: List[Dict[str, Any]] = []
    for aid, c in (deployment_floor.get("contracts") or {}).items():
        rows.append({
            "aid":           aid,
            "under":         int(bool(c.get("is_underdeployed"))),
            "cash_ratio":    _safe_f(c.get("cash_ratio")),
            "redeploy_need": _safe_f(c.get("redeploy_from_sgov_amount")),
        })
    rows.sort(key=lambda r: (-r["under"], -r["cash_ratio"], -r["redeploy_need"], r["aid"]))
    return [r["aid"] for r in rows] or ["LEGACY", "HARVEST_3", "HARVEST_5"]


def _classify_objective(
    market_mode: str,
    deployment_floor: Dict[str, Any],
    regime_memory: Dict[str, Any],
    capital_efficiency: Dict[str, Any],
    narrative: Dict[str, Any],
    deployment_pressure: Dict[str, Any],
) -> str:
    summary  = deployment_floor.get("summary") or {}
    contracts = deployment_floor.get("contracts") or {}
    eff_summary = capital_efficiency.get("summary") or {}
    rec_counts  = eff_summary.get("rotation_recommendations") or {}
    regime_sum  = regime_memory.get("summary") or {}

    deployed_ratio = _safe_f(summary.get("system_deployed_ratio"))
    n_under   = int(summary.get("total_underdeployed") or 0)
    n_over    = int(summary.get("total_over_swept") or 0)
    forced    = int(rec_counts.get("FORCE_ROTATE") or 0) + int(rec_counts.get("ROTATE") or 0)
    regime_shift = (narrative.get("regime_shift") or "NEUTRAL").upper()
    pressure_score = _safe_f(deployment_pressure.get("score"))
    transition_pressure = _safe_f(regime_sum.get("transition_pressure"))

    # 1. RECOVER_FROM_DRAWDOWN — any account is materially below base
    if any(_safe_f(c.get("live_equity")) < _safe_f(c.get("deployment_base")) - 200
           for c in contracts.values()):
        return "RECOVER_FROM_DRAWDOWN"

    # 2. DEFENSE_HARDENING — risk_off rising + vol shifting
    if regime_shift == "RISK_OFF" or market_mode in ("DEFENSIVE", "PRESERVATION"):
        return "DEFENSE_HARDENING"

    # 3. ROTATE_TO_LEADERS — multiple force_rotations queued OR strong rotation
    if forced >= 2 or (forced >= 1 and regime_shift == "ROTATION"):
        return "ROTATE_TO_LEADERS"

    # 4. DEPLOY_AGGRESSIVELY — under-deployed + ATTACK + risk_on
    if n_under >= 1 and market_mode == "ATTACK":
        return "DEPLOY_AGGRESSIVELY"
    if pressure_score >= 0.60 and deployed_ratio < 0.75:
        return "DEPLOY_AGGRESSIVELY"

    # 5. DEPLOY_SELECTIVELY — modest under-deployment in BALANCED
    if deployed_ratio < 0.72 and market_mode in ("BALANCED", "ATTACK"):
        return "DEPLOY_SELECTIVELY"

    # 6. HARVEST_AND_HOLD — well-deployed, above harvest_threshold
    above_th = sum(1 for c in contracts.values()
                     if _safe_f(c.get("live_equity")) >= _safe_f(c.get("harvest_threshold")))
    if above_th >= 1 and deployed_ratio >= 0.70:
        return "HARVEST_AND_HOLD"

    # Default: steady deployment
    return "DEPLOY_SELECTIVELY"


def build_orchestrator(
    data_dir: Path,
    multi_account_results: Optional[Dict[str, Dict[str, Any]]] = None,
    sector_lookup: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute + persist orchestrator.json."""
    n_now = now or datetime.now(timezone.utc)

    market_state       = _load_json(data_dir / "market_state.json") or {}
    deployment_floor   = _load_json(data_dir / "deployment_floor.json") or {}
    regime_memory      = _load_json(data_dir / "regime_memory.json") or {}
    capital_eff        = _load_json(data_dir / "capital_efficiency.json") or {}
    narrative          = _load_json(data_dir / "narrative_tracker.json") or {}
    sector_rotation    = _load_json(data_dir / "sector_rotation.json") or {}
    deployment_pressure = _load_json(data_dir / "deployment_pressure.json") or {}
    position_health    = _load_json(data_dir / "position_health.json") or {}

    mode = (market_state.get("mode") or "BALANCED").upper()
    defaults = POSTURE_DEFAULTS.get(mode, POSTURE_DEFAULTS["BALANCED"])

    # Adjust target exposure based on capital efficiency + transition pressure.
    target_exposure = defaults["target_exposure"]
    transition_pressure = _safe_f((regime_memory.get("summary") or {}).get("transition_pressure"))
    if transition_pressure >= 0.50:
        target_exposure = max(0.50, target_exposure - 0.10)

    stale_drag = _safe_f((capital_eff.get("summary") or {}).get("stale_holding_drag"))
    if stale_drag >= 0.30:
        target_exposure = max(0.55, target_exposure - 0.08)

    objective = _classify_objective(
        market_mode=mode,
        deployment_floor=deployment_floor,
        regime_memory=regime_memory,
        capital_efficiency=capital_eff,
        narrative=narrative,
        deployment_pressure=deployment_pressure,
    )

    # Sector targets from sector_rotation
    holdings_by_sector = _aggregate_holdings_by_sector(multi_account_results, sector_lookup)
    sys_eq = _aggregate_system_equity(deployment_floor)["equity"] or 1.0
    sector_targets: Dict[str, Dict[str, Any]] = {}
    sectors_info = (sector_rotation.get("sectors") or {})
    for sec, info in sectors_info.items():
        flow = _safe_f((info or {}).get("flow_score"))
        # Map flow_score [-1..+1] → target pct 0..25% within the exposure budget.
        # Strong sectors get up to 25% target weight; weak sectors get 0% target.
        target_pct = max(0.0, min(0.25, 0.10 + 0.15 * flow))
        # Scale by overall target_exposure budget
        target_pct = target_pct * target_exposure
        current_pct = round(holdings_by_sector.get(sec, 0.0) / sys_eq, 4)
        gap = target_pct - current_pct
        if gap > 0.05:
            action = "add"
        elif gap > 0.02:
            action = "add_slow"
        elif gap < -0.05:
            action = "trim"
        elif gap < -0.02:
            action = "trim_slow"
        else:
            action = "hold"
        sector_targets[sec] = {
            "target_pct":  round(target_pct, 4),
            "current_pct": current_pct,
            "gap":         round(gap, 4),
            "action":      action,
            "flow_score":  round(flow, 4),
        }

    # Aggregate violation flags from deployment_floor
    violations: List[str] = []
    for aid, c in (deployment_floor.get("contracts") or {}).items():
        for v in (c.get("violation_flags") or []):
            violations.append(f"{aid}:{v}")

    summary_state = {
        "system_equity":           round(sys_eq, 2),
        "system_deployed_ratio":  _safe_f((deployment_floor.get("summary") or {})
                                              .get("system_deployed_ratio")),
        "system_sgov_ratio":      round(sum(_safe_f(c.get("live_sgov"))
                                                for c in (deployment_floor.get("contracts") or {}).values())
                                            / sys_eq, 4),
        "system_idle_ratio":      round(sum(_safe_f(c.get("live_cash"))
                                                for c in (deployment_floor.get("contracts") or {}).values())
                                            / sys_eq, 4),
        "active_regimes":          [r["key"] for r in (regime_memory.get("current_regimes") or [])],
        "force_rotations_queued":  int(((capital_eff.get("summary") or {})
                                              .get("rotation_recommendations") or {})
                                              .get("FORCE_ROTATE") or 0),
        "watch_positions":         int(((capital_eff.get("summary") or {})
                                              .get("rotation_recommendations") or {})
                                              .get("WATCH") or 0),
        "violation_flags":         violations,
        "regime_stability":        _safe_f((regime_memory.get("summary") or {})
                                              .get("stability_score")),
    }

    directive = {
        "system_objective_today":         objective,
        "posture":                        defaults["posture"],
        "market_mode":                    mode,
        "target_market_exposure_pct":     round(target_exposure, 4),
        "max_sector_concentration_pct":   HARD_MAX_SECTOR_PCT,
        "max_position_concentration_pct": HARD_MAX_POSITION_PCT,
        "volatility_budget_pct":          defaults["vol_budget"],
        "deployment_pacing":              defaults["pacing"],
        "recycling_cadence_hours":        defaults["cadence_hours"],
        "account_priority_order":         _account_priority_order(deployment_floor),
    }

    bits: List[str] = []
    bits.append(f"objective={objective}")
    bits.append(f"posture={defaults['posture']}")
    bits.append(f"exposure target {target_exposure*100:.0f}%")
    if violations:
        bits.append(f"{len(violations)} violations")
    rationale = " · ".join(bits)

    payload = {
        "version":        VERSION,
        "generated_at":   n_now.isoformat(),
        "directive":      directive,
        "current_state":  summary_state,
        "sector_targets": sector_targets,
        "rationale":      rationale,
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[orchestrator] write failed: {e}")
    return payload


def load_orchestrator(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "directive": {}, "current_state": {},
             "sector_targets": {}, "rationale": "no orchestrator file"}


__all__ = [
    "VERSION", "POSTURE_DEFAULTS",
    "build_orchestrator", "load_orchestrator",
]
