"""silmaril.portfolios.global_allocator — Alpha 3.3 / 4.0 cross-account coordinator.

What it does
────────────
The Alpha 3.2 multi-account orchestrator runs the same plan list against
LEGACY, HARVEST_3, and HARVEST_5 independently. That's account-centric,
not portfolio-centric: it means three accounts can all open NVDA in the
same cycle, tripling correlated risk.

This module assigns each candidate plan to AT MOST ONE account based on
each account's strategy fit, then exposes the per-account plan slices
that the orchestrator should run.

Strategy fit
────────────
  LEGACY     (1.5% trench warfare)   → BUY/STRONG_BUY, any conviction
  HARVEST_3  (3% disciplined)        → BUY/STRONG_BUY with conviction ≥ 0.50
  HARVEST_5  (5% conviction-only)    → STRONG_BUY, conviction ≥ 0.60,
                                        OR elite-tagged regardless of conviction

Alpha 4.0 changes
─────────────────
  - `max_opens_per_cycle` scales with market_mode and deployment_pressure:
      ATTACK + high pressure → caps × 2
      ATTACK                 → caps × 1.5
      BALANCED + high press. → caps × 1.5
      DEFENSIVE              → caps × 0.7
      PRESERVATION           → 0  (no opens, regardless of fit)
  - `urgency_tickers` (from policy_router) receive priority assignment
    after elite tickers but before generic high-conviction plans.
  - The function accepts a `policy` arg; legacy callers without it still
    get 3.3 behaviour.

Assignment rules
────────────────
  1. Elite-tagged plans go to HARVEST_5 first (concentrated bets).
  2. Urgency-tagged (Alpha 4.0) plans next, scored by fit + urgency.
  3. STRONG_BUY + high conviction plans routed by score, top first,
     until each account is at its open-cap.
  4. Lower-conviction BUYs go to LEGACY (trench warfare = many small).
  5. A plan is assigned to AT MOST ONE account.

Result is published to docs/data/global_allocation.json so the
dashboard can show which account got which trade, and why.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _safe_f(x, default=0.0) -> float:
    try:
        f = float(x)
        if f != f:
            return default
        return f
    except Exception:
        return default


# ── Account fitness scoring ──────────────────────────────────────────

_ACCOUNT_FITNESS = {
    "LEGACY": {
        "preferred_signals":      ("BUY", "STRONG_BUY"),
        "min_conviction":         0.40,
        "elite_priority":         1,     # lowest — does NOT take elites first
        "max_opens_per_cycle":    3,
        "score_bonus_for_elite":  0.0,
        "score_bonus_for_trend":  0.10,
        "score_bonus_for_urgency": 0.10,
    },
    "HARVEST_3": {
        "preferred_signals":      ("BUY", "STRONG_BUY"),
        "min_conviction":         0.50,
        "elite_priority":         2,
        "max_opens_per_cycle":    2,
        "score_bonus_for_elite":  0.15,
        "score_bonus_for_trend":  0.15,
        "score_bonus_for_urgency": 0.15,
    },
    "HARVEST_5": {
        "preferred_signals":      ("STRONG_BUY",),
        "min_conviction":         0.60,
        "elite_priority":         3,     # highest — gets first dibs on elites
        "max_opens_per_cycle":    1,
        "score_bonus_for_elite":  0.30,
        "score_bonus_for_trend":  0.20,
        "score_bonus_for_urgency": 0.25,
    },
}


# Alpha 4.0: mode + pressure → cap multiplier
def _cap_multiplier(market_mode: str, pressure_high: bool) -> float:
    mode = (market_mode or "BALANCED").upper()
    if mode == "PRESERVATION":
        return 0.0
    if mode == "ATTACK":
        return 2.0 if pressure_high else 1.5
    if mode == "BALANCED":
        return 1.5 if pressure_high else 1.0
    if mode == "DEFENSIVE":
        return 0.7
    return 1.0


def _scaled_cap(base: int, mult: float) -> int:
    if mult <= 0:
        return 0
    # Always at least 1 if base > 0 and mult > 0; ceiling so 1.5 → 2 not 1.
    return max(1, int(math.ceil(base * mult)))


def _account_score(
    plan: Dict[str, Any], aid: str,
    elite_tickers: List[str], urgency_tickers: List[str],
) -> float:
    """Score how well this plan fits this account. Higher = better fit."""
    f = _ACCOUNT_FITNESS.get(aid, _ACCOUNT_FITNESS["LEGACY"])
    sig = (plan.get("consensus_signal") or "").upper()
    conv = _safe_f(plan.get("consensus_conviction") or plan.get("avg_conviction"))
    ticker = (plan.get("ticker") or "").upper()
    three_m = plan.get("three_month_signal", "unknown")

    if sig not in f["preferred_signals"]:
        return -1.0
    if conv < f["min_conviction"]:
        return -1.0

    # Base = conviction
    score = conv
    # Bonuses
    if ticker in elite_tickers:
        score += f["score_bonus_for_elite"]
    if ticker in urgency_tickers:
        score += f["score_bonus_for_urgency"]
    if three_m == "uptrend":
        score += f["score_bonus_for_trend"]
    return round(score, 4)


def allocate_plans_to_accounts(
    plans: List[Dict[str, Any]],
    enabled_accounts: List[str],
    *,
    elite_tickers: Optional[List[str]] = None,
    urgency_priority_order: Optional[List[str]] = None,
    urgency_tickers: Optional[List[str]] = None,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Decide which plan goes to which account.

    Alpha 4.0 args:
      - urgency_tickers: list of tickers tagged by policy_router as
        deployment-urgency priority (from `policy.urgency_tickers`).
      - policy: the full execution_policy dict. Used to scale caps by
        market_mode and deployment_pressure.high.

    Returns:
      {
        "by_account":     {"LEGACY": [plan, plan], "HARVEST_3": [plan], ...},
        "assignments":    [{"ticker":"NVDA","account":"HARVEST_5","score":0.95,
                             "rationale":"elite + STRONG_BUY 0.71"}, ...],
        "unassigned":     [{"ticker":"...","reason":"..."}, ...],
        "caps":           {"LEGACY": 4, "HARVEST_3": 3, "HARVEST_5": 2},
        "used":           {"LEGACY": 2, "HARVEST_3": 1, "HARVEST_5": 1},
        "cap_multiplier": 1.5,
      }
    """
    elite_tickers = elite_tickers or []
    urgency_tickers = urgency_tickers or (
        (policy or {}).get("urgency_tickers") or [])
    enabled = [a for a in enabled_accounts if a in _ACCOUNT_FITNESS]
    if not enabled:
        return {"by_account": {}, "assignments": [], "unassigned": [],
                "caps": {}, "used": {}, "cap_multiplier": 0.0}

    # Alpha 4.0: compute cap multiplier from policy
    market_mode  = ((policy or {}).get("market_mode") or "BALANCED").upper()
    pressure_high = bool(((policy or {}).get("deployment_pressure") or {}).get("high"))
    cap_mult = _cap_multiplier(market_mode, pressure_high)

    # Track how many opens each account has used
    used = {a: 0 for a in enabled}
    caps = {a: _scaled_cap(_ACCOUNT_FITNESS[a]["max_opens_per_cycle"], cap_mult)
            for a in enabled}
    by_account: Dict[str, List[Dict[str, Any]]] = {a: [] for a in enabled}
    assignments: List[Dict[str, Any]] = []
    unassigned: List[Dict[str, Any]] = []

    # If we're in PRESERVATION (cap_mult == 0), short-circuit.
    if cap_mult <= 0.0:
        for p in plans:
            t = (p.get("ticker") or "").upper()
            if t:
                unassigned.append({
                    "ticker": t,
                    "reason": f"market_mode={market_mode}: opens suspended",
                    "plan_signal":     p.get("consensus_signal"),
                    "plan_conviction": p.get("consensus_conviction"),
                })
        return {"by_account": by_account, "assignments": assignments,
                "unassigned": unassigned, "caps": caps, "used": used,
                "cap_multiplier": cap_mult,
                "market_mode": market_mode,
                "pressure_high": pressure_high}

    # Build a ranking: elite tickers first (in urgency order), then urgency-
    # tagged, then remaining plans sorted by max account score.
    ticker_to_plan = {(p.get("ticker") or "").upper(): p for p in plans
                       if p.get("ticker")}
    seen: set = set()
    ordered_tickers: List[str] = []

    # 1. Elite tickers in urgency order
    urgency_order = urgency_priority_order or []
    for t in urgency_order:
        if t in elite_tickers and t in ticker_to_plan and t not in seen:
            ordered_tickers.append(t)
            seen.add(t)
    # Any remaining elites not in urgency list
    for t in elite_tickers:
        if t in ticker_to_plan and t not in seen:
            ordered_tickers.append(t)
            seen.add(t)
    # 2. Alpha 4.0: urgency-tagged (pressure-driven) tickers next
    for t in urgency_tickers:
        if t in ticker_to_plan and t not in seen:
            ordered_tickers.append(t)
            seen.add(t)
    # 3. Non-elite in urgency order
    for t in urgency_order:
        if t in ticker_to_plan and t not in seen:
            ordered_tickers.append(t)
            seen.add(t)
    # 4. Anything else
    for p in plans:
        t = (p.get("ticker") or "").upper()
        if t and t not in seen:
            ordered_tickers.append(t)
            seen.add(t)

    # Assign each plan to the best-fit available account
    for ticker in ordered_tickers:
        plan = ticker_to_plan.get(ticker)
        if not plan:
            continue
        is_elite = ticker in elite_tickers
        is_urgent = ticker in urgency_tickers
        candidates: List = []  # (priority_for_this_plan, account_score, account_id)
        for aid in enabled:
            if used[aid] >= caps[aid]:
                continue
            score = _account_score(plan, aid, elite_tickers, urgency_tickers)
            if score < 0:
                continue
            # Elite priority: HARVEST_5 ranks highest for elites
            # Urgent priority: HARVEST_3 ranks highest for urgent (mid risk/reward)
            if is_elite:
                priority = _ACCOUNT_FITNESS[aid]["elite_priority"]
            elif is_urgent:
                # HARVEST_3 (priority 2) is the natural home for urgency tickets;
                # they're conviction-validated but not necessarily elite.
                priority = 2 if aid == "HARVEST_3" else (
                    3 if aid == "HARVEST_5" else 1)
            else:
                priority = 0
            candidates.append((priority, score, aid))
        if not candidates:
            unassigned.append({
                "ticker": ticker,
                "reason": "no enabled account meets fitness for this plan",
                "plan_signal":     plan.get("consensus_signal"),
                "plan_conviction": plan.get("consensus_conviction"),
            })
            continue
        # Highest priority first, then highest score, then alphabetical for stability
        candidates.sort(key=lambda c: (-c[0], -c[1], c[2]))
        _, best_score, best_aid = candidates[0]
        by_account[best_aid].append(plan)
        used[best_aid] += 1
        tags = []
        if is_elite:    tags.append("elite")
        if is_urgent:   tags.append("urgent")
        tags_str = " + ".join(tags) + " " if tags else ""
        assignments.append({
            "ticker":   ticker,
            "account":  best_aid,
            "score":    best_score,
            "is_elite": is_elite,
            "is_urgent": is_urgent,
            "rationale": (
                f"{tags_str}"
                f"{plan.get('consensus_signal', '?')} "
                f"conv {plan.get('consensus_conviction', 0):.2f} "
                f"→ best fit {best_aid} (score {best_score:.2f}) "
                f"[cap×{cap_mult:.2f}]"
            ),
        })

    return {
        "by_account":     by_account,
        "assignments":    assignments,
        "unassigned":     unassigned,
        "caps":           caps,
        "used":           used,
        "cap_multiplier": cap_mult,
        "market_mode":    market_mode,
        "pressure_high":  pressure_high,
    }


def write_global_allocation(
    data_dir: Path,
    allocation: Dict[str, Any],
) -> None:
    """Persist the allocation result for dashboard rendering."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version":      "4.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            # By-account is stored as TICKER lists (not full plans) so the
            # file stays small and dashboard-friendly.
            "assignments": allocation.get("assignments", []),
            "unassigned":  allocation.get("unassigned", []),
            "by_account_tickers": {
                aid: [(p.get("ticker") or "").upper()
                      for p in (plans or [])]
                for aid, plans in (allocation.get("by_account") or {}).items()
            },
            "caps":            allocation.get("caps", {}),
            "used":            allocation.get("used", {}),
            "cap_multiplier":  allocation.get("cap_multiplier", 1.0),
            "market_mode":     allocation.get("market_mode", "BALANCED"),
            "pressure_high":   allocation.get("pressure_high", False),
        }
        (data_dir / "global_allocation.json").write_text(
            json.dumps(payload, indent=2, default=str))
    except Exception as e:
        print(f"[global_allocator] write failed: {e}")


__all__ = [
    "allocate_plans_to_accounts",
    "write_global_allocation",
]
