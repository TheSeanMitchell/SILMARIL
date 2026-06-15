"""silmaril.portfolios.deployment_floor — Alpha 6.0 account contract.

Hard-coded identity per master directive:

    Account 1 (LEGACY)    — 1.5% Daily Harvester
                            base $10,000 · harvest above $10,150
    Account 2 (HARVEST_3) — 3% Strategic Harvester
                            base $10,000 · harvest above $10,300
    Account 3 (HARVEST_5) — 5% Conviction Harvester
                            base $10,000 · harvest above $10,500

Anti-failure modes baked in:
    NOT — sweeping entire book
    NOT — shrinking deployable capital
    NOT — freezing in SGOV
    NOT — ratcheting into inactivity

Alpha 6.0 additions:
    NEGATIVE_CASH:        cash < 0 (margin used) → halt opens, alert
    MARGIN_USED_SEVERE:   deployed_ratio > 1.10 → emergency unwind
    DRIFT_FROM_OBJECTIVE: account's actual objective ≠ contract objective
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


VERSION  = "6.0"
FILENAME = "deployment_floor.json"

ACCOUNT_CONTRACTS: Dict[str, Dict[str, float]] = {
    "LEGACY": {
        "deployment_base":         10_000.0,
        "min_harvest_gain_pct":    0.015,
        "max_sgov_ratio":          0.35,
        "minimum_deployed_ratio":  0.65,
        "target_market_exposure":  0.80,
        "redeploy_idle_threshold": 0.20,
    },
    "HARVEST_3": {
        "deployment_base":         10_000.0,
        "min_harvest_gain_pct":    0.03,
        "max_sgov_ratio":          0.35,
        "minimum_deployed_ratio":  0.65,
        "target_market_exposure":  0.75,
        "redeploy_idle_threshold": 0.25,
    },
    "HARVEST_5": {
        "deployment_base":         10_000.0,
        "min_harvest_gain_pct":    0.05,
        "max_sgov_ratio":          0.30,
        "minimum_deployed_ratio":  0.70,
        "target_market_exposure":  0.85,
        "redeploy_idle_threshold": 0.20,
    },
}


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


def compute_contract(
    account_id: str,
    equity: float,
    cash: float,
    sgov_value: float,
    pre_cycle_sgov_value: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute per-cycle contract for one account."""
    cfg = ACCOUNT_CONTRACTS.get(account_id) or ACCOUNT_CONTRACTS["LEGACY"]
    base = _safe_f(cfg["deployment_base"])
    gain_pct = _safe_f(cfg["min_harvest_gain_pct"])
    max_sgov = _safe_f(cfg["max_sgov_ratio"])
    min_dep  = _safe_f(cfg["minimum_deployed_ratio"])
    target   = _safe_f(cfg["target_market_exposure"])
    idle_thr = _safe_f(cfg["redeploy_idle_threshold"])

    equity = _safe_f(equity)
    cash   = _safe_f(cash)
    sgov   = _safe_f(sgov_value)

    harvest_threshold = base + (gain_pct * base)

    # CORE RULE: max_sweep_today = max(0, equity - deployment_base)
    max_sweep_today = max(0.0, equity - base)

    deployed = max(0.0, equity - cash - sgov)
    deployed_ratio = (deployed / equity) if equity > 0 else 0.0
    sgov_ratio     = (sgov / equity) if equity > 0 else 0.0
    cash_ratio     = (cash / equity) if equity > 0 else 0.0

    is_underdeployed = (deployed_ratio < min_dep) or (cash_ratio > idle_thr)
    # Don't flag underdeployed if cash is negative (we're over-leveraged, not idle)
    if cash < 0:
        is_underdeployed = False

    redeploy_from_sgov = 0.0
    if equity < base and sgov > 0:
        shortfall = base - equity
        redeploy_from_sgov = min(sgov, shortfall + 200.0)
    elif sgov_ratio > max_sgov:
        excess = sgov - (equity * max_sgov)
        redeploy_from_sgov = max(redeploy_from_sgov, excess)
    redeploy_from_sgov = round(max(0.0, redeploy_from_sgov), 2)

    # Decide today's objective.
    if cash < 0:
        # New: margin used → emergency unwind objective
        objective = "EMERGENCY_UNWIND_MARGIN"
    elif equity < base - 200:
        objective = "REDEPLOY_FROM_SGOV"
    elif is_underdeployed:
        objective = "DEPLOY_IDLE_CAPITAL"
    elif equity >= harvest_threshold:
        objective = "HARVEST_OVERAGE"
    else:
        objective = "STEADY_STATE"

    # Violation detection
    flags: List[str] = []
    over_sweep_amount = 0.0
    if pre_cycle_sgov_value is not None:
        delta_sgov = max(0.0, sgov - _safe_f(pre_cycle_sgov_value))
        if delta_sgov > max_sweep_today + 1.50:
            flags.append("OVER_SWEPT")
            over_sweep_amount = round(delta_sgov - max_sweep_today, 2)
    if is_underdeployed and equity > base:
        flags.append("UNDERDEPLOYED")
    if sgov_ratio > max_sgov:
        flags.append("SGOV_RATIO_EXCEEDED")
    if equity < base - 500:
        flags.append("BELOW_BASE_SEVERE")
    # Alpha 6.0 additions
    if cash < -1.0:
        flags.append("NEGATIVE_CASH")
    if deployed_ratio > 1.10:
        flags.append("MARGIN_USED_SEVERE")
    elif deployed_ratio > 1.02:
        flags.append("MARGIN_USED")
    if cash > 0 and deployed > 0 and cash_ratio > 0.50 and equity > base:
        flags.append("STRANDED_CAPITAL")

    must_redeploy_today = objective in (
        "REDEPLOY_FROM_SGOV", "DEPLOY_IDLE_CAPITAL", "EMERGENCY_UNWIND_MARGIN")

    bits: List[str] = []
    if cash < 0:
        bits.append(f"MARGIN USED · cash ${cash:.0f}")
    if max_sweep_today > 0:
        bits.append(f"sweep cap ${max_sweep_today:.0f}")
    if redeploy_from_sgov > 0:
        bits.append(f"redeploy ${redeploy_from_sgov:.0f} from SGOV")
    if is_underdeployed:
        bits.append(f"underdeployed {deployed_ratio*100:.0f}% < {min_dep*100:.0f}%")
    if deployed_ratio > 1.0:
        bits.append(f"OVER-DEPLOYED {deployed_ratio*100:.0f}%")
    if flags:
        bits.append("VIOLATIONS: " + ", ".join(flags))
    if not bits:
        bits.append("steady · within all bands")
    rationale = " · ".join(bits)

    return {
        "account_id":                account_id,
        "deployment_base":           base,
        "harvest_threshold":         harvest_threshold,
        "min_harvest_gain_pct":      gain_pct,
        "max_sgov_ratio":            max_sgov,
        "minimum_deployed_ratio":    min_dep,
        "target_market_exposure":    target,
        "live_equity":               round(equity, 2),
        "live_cash":                 round(cash, 2),
        "live_sgov":                 round(sgov, 2),
        "deployed":                  round(deployed, 2),
        "deployed_ratio":            round(deployed_ratio, 4),
        "sgov_ratio":                round(sgov_ratio, 4),
        "cash_ratio":                round(cash_ratio, 4),
        "max_sweep_today":           round(max_sweep_today, 2),
        "redeploy_from_sgov_amount": redeploy_from_sgov,
        "is_underdeployed":          bool(is_underdeployed),
        "must_redeploy_today":       bool(must_redeploy_today),
        "objective_today":           objective,
        "violation_flags":           flags,
        "over_sweep_amount":         over_sweep_amount,
        "rationale":                 rationale,
    }


def build_deployment_floor(
    data_dir: Path,
    multi_account_results: Optional[Dict[str, Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    n_now = now or datetime.now(timezone.utc)
    prior = _load_json(data_dir / FILENAME) or {}
    prior_contracts = (prior.get("contracts") or {}) if isinstance(prior, dict) else {}

    contracts: Dict[str, Dict[str, Any]] = {}
    if isinstance(multi_account_results, dict):
        for aid, astate in multi_account_results.items():
            if not isinstance(astate, dict):
                continue
            if not astate.get("enabled") and not astate.get("configured"):
                continue
            acct = astate.get("account") or {}
            vault = astate.get("savings_vault") or astate.get("live_vault") or {}
            equity = _safe_f(acct.get("equity") or astate.get("equity"))
            cash   = _safe_f(acct.get("cash") or astate.get("cash"))
            sgov   = _safe_f(vault.get("total_market_value")
                              or astate.get("verified_harvested"))
            prior_sgov = _safe_f((prior_contracts.get(aid) or {}).get("live_sgov"))
            contracts[aid] = compute_contract(
                account_id=aid, equity=equity, cash=cash,
                sgov_value=sgov, pre_cycle_sgov_value=prior_sgov,
            )

    total_eq = sum(_safe_f(c.get("live_equity")) for c in contracts.values())
    total_dep = sum(_safe_f(c.get("deployed")) for c in contracts.values())
    total_under = sum(1 for c in contracts.values() if c.get("is_underdeployed"))
    total_over  = sum(1 for c in contracts.values()
                       if "OVER_SWEPT" in (c.get("violation_flags") or []))
    total_negative_cash = sum(1 for c in contracts.values()
                                if "NEGATIVE_CASH" in (c.get("violation_flags") or []))
    total_margin = sum(1 for c in contracts.values()
                        if any(f in (c.get("violation_flags") or [])
                                for f in ("MARGIN_USED", "MARGIN_USED_SEVERE")))
    summary = {
        "configured_accounts":    len(contracts),
        "system_equity_total":    round(total_eq, 2),
        "system_deployed_total":  round(total_dep, 2),
        "system_deployed_ratio":  round((total_dep / total_eq) if total_eq > 0 else 0.0, 4),
        "total_underdeployed":    total_under,
        "total_over_swept":       total_over,
        "total_negative_cash":    total_negative_cash,
        "total_margin_used":      total_margin,
    }

    payload = {
        "version":      VERSION,
        "generated_at": n_now.isoformat(),
        "contracts":    contracts,
        "summary":      summary,
    }
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / FILENAME).write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[deployment_floor] write failed: {e}")
    return payload


def get_contract(data_dir: Path, account_id: str) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return (body.get("contracts") or {}).get(account_id, {})
    return {}


def load_deployment_floor(data_dir: Path) -> Dict[str, Any]:
    body = _load_json(data_dir / FILENAME)
    if isinstance(body, dict):
        return body
    return {"version": VERSION, "contracts": {},
             "summary": {"configured_accounts": 0,
                          "system_deployed_ratio": 0.0}}


__all__ = [
    "VERSION", "ACCOUNT_CONTRACTS",
    "compute_contract", "build_deployment_floor",
    "get_contract", "load_deployment_floor",
]
