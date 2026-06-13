"""silmaril.portfolios.deployment_pressure — Alpha 4.0 capital-deployment urgency engine.

What it does
────────────
The Alpha 3.x architecture answers "why should we OPEN this position?"
This module answers the equally important inverse: "why is this capital
NOT deployed?"

It runs after `market_state` is classified and BEFORE `policy_router`
arbitrates so the policy can include a `deployment_pressure` score and
an escalation directive when the system has stagnated.

The score combines:
  - idle cash percentage across all enabled accounts
  - SGOV exposure as % of total book (capital parked, not working)
  - count of elite-quality opportunities available this cycle
  - current market_state mode (ATTACK adds pressure; PRESERVATION removes it)
  - portfolio vulnerability count (high vulnerability bleeds pressure)

A score ≥ 0.60 indicates the system should:
  - relax non-critical preservation suppression
  - widen concentration limits
  - reduce min_conviction_floor for opens
  - boost dynamic_sizer's pressure scaler
  - recommend SGOV redeployment back to cash if exposure is elevated

This module is PURE and DETERMINISTIC. No LLM. No synthetic intelligence.
Every input is an integer or float read from existing JSON sidecars; every
output is auditable. The score's components are persisted so the dashboard
can show exactly why pressure is high or low.

Output (docs/data/deployment_pressure.json)
───────────────────────────────────────────
{
  "version":   "4.0",
  "generated_at": "...",
  "score":     0.0..1.0,
  "high":      bool,                       # score >= 0.60
  "components": {
     "idle_cash":         0.0..1.0,
     "sgov_exposure":     0.0..1.0,
     "elite_pipeline":    0.0..1.0,
     "market_mode_bias":  -0.20..+0.20,
     "vulnerability_drag": -0.20..0.0,
  },
  "totals": {
     "trading_capital_total": 30000.0,
     "idle_cash_total":       4200.0,
     "sgov_value_total":      6800.0,
     "elite_count":           2,
     "vulnerable_count":      0,
  },
  "actions": [
     {"action": "RELAX_SUPPRESSION", "rationale": "..."},
     {"action": "REDEPLOY_SGOV",     "rationale": "...", "amount_hint": 1500.0},
     {"action": "WIDEN_CONCENTRATION","rationale": "..."},
  ],
  "rationale": "humanly readable summary string"
}

Hard rules (preserve the 1.5/3/5 harvester philosophy)
──────────────────────────────────────────────────────
  - The principal floor is sacred — pressure can NEVER recommend
    deploying below `principal_target * 0.95`.
  - SGOV redeployment recommendations are CAPPED at 25% of the vault
    per cycle and only fire in ATTACK mode with score >= 0.70.
  - Pressure cannot create new positions; it can only reduce friction
    on positions that other engines already want to open.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


VERSION = "4.0"

# ─── Thresholds ──────────────────────────────────────────────────────

HIGH_PRESSURE_THRESHOLD       = 0.60   # score >= this triggers escalation
SGOV_REDEPLOY_THRESHOLD       = 0.70   # score >= this allows SGOV redeployment
SGOV_REDEPLOY_MAX_PCT         = 0.25   # max fraction of vault we recommend peeling per cycle
SGOV_MIN_REDEPLOY_USD         = 100.0  # don't bother with tiny redeployments

# Idle-cash thresholds (as fraction of trading_capital).
# Below LOW = no pressure from idle cash. Above HIGH = saturated contribution.
IDLE_CASH_LOW                 = 0.05   # 5% cash is normal slippage
IDLE_CASH_HIGH                = 0.30   # 30% cash = unambiguously underdeployed

# SGOV exposure thresholds (as fraction of total book = trading_capital + sgov).
SGOV_EXPOSURE_LOW             = 0.15   # under 15% = harvested savings working
SGOV_EXPOSURE_HIGH            = 0.50   # over 50% = capital parked, not earning

# Elite pipeline contribution.
ELITE_FULL_SCORE_AT_COUNT     = 3      # 3+ elite tickers in the pipeline = full credit

# Market-mode biases.
_MODE_BIAS: Dict[str, float] = {
    "ATTACK":       +0.20,
    "BALANCED":     +0.05,
    "DEFENSIVE":    -0.10,
    "PRESERVATION": -0.20,
}

# Weights for the four positive components (they sum to 1.0).
W_IDLE_CASH      = 0.40
W_SGOV_EXPOSURE  = 0.25
W_ELITE_PIPELINE = 0.20
W_MODE_BIAS      = 0.15  # bias contribution scaled into the weighted sum


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


def _idle_cash_score(idle_cash_total: float, trading_capital_total: float) -> float:
    """0.0 at IDLE_CASH_LOW or below, linear ramp to 1.0 at IDLE_CASH_HIGH."""
    if trading_capital_total <= 0:
        return 0.0
    ratio = idle_cash_total / trading_capital_total
    if ratio <= IDLE_CASH_LOW:
        return 0.0
    if ratio >= IDLE_CASH_HIGH:
        return 1.0
    span = IDLE_CASH_HIGH - IDLE_CASH_LOW
    return (ratio - IDLE_CASH_LOW) / span


def _sgov_exposure_score(sgov_value_total: float,
                          trading_capital_total: float) -> float:
    """0.0 at SGOV_EXPOSURE_LOW or below, ramp to 1.0 at SGOV_EXPOSURE_HIGH.

    Note: divisor is `trading_capital + sgov` — total invested book.
    """
    book = max(0.01, trading_capital_total + sgov_value_total)
    ratio = sgov_value_total / book
    if ratio <= SGOV_EXPOSURE_LOW:
        return 0.0
    if ratio >= SGOV_EXPOSURE_HIGH:
        return 1.0
    span = SGOV_EXPOSURE_HIGH - SGOV_EXPOSURE_LOW
    return (ratio - SGOV_EXPOSURE_LOW) / span


def _elite_pipeline_score(elite_count: int) -> float:
    """0.0 at no elites, 1.0 at ELITE_FULL_SCORE_AT_COUNT or more."""
    if elite_count <= 0:
        return 0.0
    return _clamp(elite_count / ELITE_FULL_SCORE_AT_COUNT)


def _vulnerability_drag(vulnerable_count: int) -> float:
    """Each vulnerable position reduces pressure by 0.05, max drag -0.20.

    Rationale: if you're already exposed to critical risk, deploying more
    capital is not the right response — defend what's at risk first.
    """
    return max(-0.20, -0.05 * float(vulnerable_count or 0))


def _gather_totals(
    multi_account_results: Dict[str, Dict[str, Any]],
) -> Tuple[float, float, float]:
    """Sum trading_capital, cash, and SGOV market value across enabled accounts.

    Returns (trading_capital_total, idle_cash_total, sgov_value_total).
    """
    tc = 0.0
    cash = 0.0
    sgov = 0.0
    for aid, astate in (multi_account_results or {}).items():
        if not isinstance(astate, dict) or not astate.get("enabled"):
            continue
        tc += _safe_f(astate.get("trading_capital"))
        acct = astate.get("account") or {}
        cash += _safe_f(acct.get("cash"))
        vault = astate.get("savings_vault") or {}
        sgov += _safe_f(vault.get("total_market_value"))
    return round(tc, 2), round(cash, 2), round(sgov, 2)


def compute_pressure(
    *,
    market_state: Dict[str, Any],
    multi_account_results: Dict[str, Dict[str, Any]],
    elite_tickers: Optional[List[str]] = None,
    profit_at_risk: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compute the deployment-pressure scorecard.

    All inputs are dicts already produced by upstream sidecars; no
    additional I/O is performed here. Pure function except optional
    `now` injection for tests.
    """
    elite_tickers = elite_tickers or []
    profit_at_risk = profit_at_risk or {}
    mode = (market_state.get("mode") or "BALANCED").upper()

    tc_total, idle_cash, sgov_value = _gather_totals(multi_account_results)
    vulnerable_count = sum(
        1 for p in (profit_at_risk.get("positions") or [])
        if isinstance(p, dict) and p.get("vulnerable"))
    elite_count = len(elite_tickers)

    s_idle    = _idle_cash_score(idle_cash, tc_total)
    s_sgov    = _sgov_exposure_score(sgov_value, tc_total)
    s_elite   = _elite_pipeline_score(elite_count)
    bias      = _MODE_BIAS.get(mode, 0.0)
    drag      = _vulnerability_drag(vulnerable_count)

    # Weighted positive contribution.
    positive = (
        W_IDLE_CASH      * s_idle
        + W_SGOV_EXPOSURE * s_sgov
        + W_ELITE_PIPELINE * s_elite
        + W_MODE_BIAS     * max(0.0, bias / 0.20)   # bias normalised 0..1
    )
    # Negative contributions: mode penalty when bias < 0; vulnerability drag.
    negative = min(0.0, bias) + drag

    score = _clamp(positive + negative, 0.0, 1.0)
    score = round(score, 4)
    high = score >= HIGH_PRESSURE_THRESHOLD

    # ── Build action list ─────────────────────────────────────────────
    actions: List[Dict[str, Any]] = []
    if high and mode != "PRESERVATION":
        actions.append({
            "action": "RELAX_SUPPRESSION",
            "rationale": (
                f"Deployment pressure {score:.2f} ≥ {HIGH_PRESSURE_THRESHOLD:.2f} in "
                f"{mode}: relax non-critical preservation suppression so "
                f"strong setups can deploy."),
        })
    if high and elite_count > 0 and mode in ("ATTACK", "BALANCED"):
        actions.append({
            "action": "WIDEN_CONCENTRATION",
            "rationale": (
                f"{elite_count} elite-tagged opportunit{'ies' if elite_count != 1 else 'y'} "
                f"and pressure {score:.2f}: widen per-sector and per-account caps."),
        })
    if (score >= SGOV_REDEPLOY_THRESHOLD
        and mode == "ATTACK"
        and sgov_value > 0
        and s_sgov >= 0.30):
        amount_hint = round(sgov_value * SGOV_REDEPLOY_MAX_PCT, 2)
        if amount_hint >= SGOV_MIN_REDEPLOY_USD:
            actions.append({
                "action": "REDEPLOY_SGOV",
                "rationale": (
                    f"ATTACK mode + pressure {score:.2f} + SGOV exposure "
                    f"score {s_sgov:.2f}: recommend peeling ${amount_hint:.2f} "
                    f"({SGOV_REDEPLOY_MAX_PCT*100:.0f}% of vault) back to cash."),
                "amount_hint": amount_hint,
            })
    if high and s_idle >= 0.5:
        actions.append({
            "action": "ESCALATE_OPENS",
            "rationale": (
                f"Idle cash score {s_idle:.2f} with pressure {score:.2f}: "
                f"reduce min_conviction_floor and boost size scaler."),
        })

    rationale_bits: List[str] = [f"mode={mode}", f"score={score:.2f}"]
    if s_idle >= 0.4:
        rationale_bits.append(f"idle cash {s_idle:.2f}")
    if s_sgov >= 0.4:
        rationale_bits.append(f"SGOV exposure {s_sgov:.2f}")
    if elite_count:
        rationale_bits.append(f"{elite_count} elite")
    if vulnerable_count:
        rationale_bits.append(f"{vulnerable_count} vulnerable")
    rationale = " · ".join(rationale_bits)

    n = now or datetime.now(timezone.utc)
    return {
        "version": VERSION,
        "generated_at": n.isoformat(),
        "score": score,
        "high": bool(high),
        "components": {
            "idle_cash":          round(s_idle, 4),
            "sgov_exposure":      round(s_sgov, 4),
            "elite_pipeline":     round(s_elite, 4),
            "market_mode_bias":   round(bias, 4),
            "vulnerability_drag": round(drag, 4),
        },
        "totals": {
            "trading_capital_total": tc_total,
            "idle_cash_total":       idle_cash,
            "sgov_value_total":      sgov_value,
            "elite_count":           int(elite_count),
            "vulnerable_count":      int(vulnerable_count),
        },
        "thresholds": {
            "high":            HIGH_PRESSURE_THRESHOLD,
            "sgov_redeploy":   SGOV_REDEPLOY_THRESHOLD,
            "idle_cash_low":   IDLE_CASH_LOW,
            "idle_cash_high":  IDLE_CASH_HIGH,
            "sgov_low":        SGOV_EXPOSURE_LOW,
            "sgov_high":       SGOV_EXPOSURE_HIGH,
        },
        "actions":   actions,
        "rationale": rationale,
    }


def write_pressure(
    data_dir: Path,
    pressure: Dict[str, Any],
) -> None:
    """Persist the pressure dict to docs/data/deployment_pressure.json."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "deployment_pressure.json").write_text(
            json.dumps(pressure, indent=2, default=str))
    except Exception as e:
        print(f"[deployment_pressure] write failed: {e}")


def load_pressure(data_dir: Path) -> Dict[str, Any]:
    """Read deployment_pressure.json. Returns a safe default if missing."""
    p = data_dir / "deployment_pressure.json"
    if not p.exists():
        return _default_pressure()
    try:
        return json.loads(p.read_text())
    except Exception:
        return _default_pressure()


def _default_pressure() -> Dict[str, Any]:
    return {
        "version": VERSION,
        "score": 0.0,
        "high":  False,
        "components": {},
        "totals":     {},
        "thresholds": {
            "high":          HIGH_PRESSURE_THRESHOLD,
            "sgov_redeploy": SGOV_REDEPLOY_THRESHOLD,
        },
        "actions":   [],
        "rationale": "default (no pressure file)",
    }


__all__ = [
    "VERSION",
    "HIGH_PRESSURE_THRESHOLD",
    "SGOV_REDEPLOY_THRESHOLD",
    "compute_pressure",
    "write_pressure",
    "load_pressure",
]
