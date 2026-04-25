"""
silmaril.risk.engine — Hard risk constraints applied to every agent.

This is the layer that makes the difference between a "system" and a
"casino with extra steps." Every action is gated through these rules:

  POSITION SIZING
    - Max single-trade allocation:    25% of book
    - Min cash buffer to keep:        0% (agents can be fully invested)

  DAILY DRAWDOWN
    - If equity falls by more than 8% in a single day, the agent is
      FROZEN for the rest of the cycle. Existing positions keep their
      current marks; no new trades are taken.
    - The freeze persists until equity recovers by 4% from the trigger
      level (so we don't get whipsawed back into trading)

  TRACK-RECORD KILL SWITCH
    - Phase C produces a weight multiplier per agent based on win rate
      and EV. If that multiplier drops below KILL_WEIGHT_THRESHOLD, the
      agent is FROZEN. This auto-recovers if their multiplier comes back.

  COHORT KILL SWITCH
    - If the cohort average return drops more than COHORT_DD_THRESHOLD,
      the entire system enters SAFE MODE: no new positions opened by
      anyone, existing positions hold. This is the "regime broke,
      something is structurally wrong, stop digging" emergency.

Risk state is persisted to risk_state.json. The dashboard reads it to
show frozen agents and any active kill switches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json


# ─────────────────────────────────────────────────────────────────
# Configuration — tuned conservatively. Editable per deployment.
# ─────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    # Position sizing
    "max_single_position_pct": 0.25,          # 25% of book per trade
    "min_cash_buffer_pct":     0.00,
    # Daily drawdown
    "daily_drawdown_freeze_pct":   0.08,      # -8% in a day → freeze
    "daily_drawdown_unfreeze_pct": 0.04,      # need to rebound +4% to unfreeze
    # Track-record kill switch
    "kill_weight_threshold":   0.85,          # weight multiplier below 0.85 → freeze
    "kill_min_calls":          15,            # but only after 15 scored calls
    # Cohort kill switch (system-wide safe mode)
    "cohort_dd_threshold":     0.05,          # cohort avg return below -5% → SAFE MODE
    "cohort_dd_min_runs":      5,             # only after 5 days of data
    # Plan-level constraints
    "min_reward_risk":         1.5,           # plans below 1.5:1 R:R get rejected
    "max_risk_per_plan_pct":   0.02,          # 2% portfolio risk cap per plan
}


# ─────────────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────────────

@dataclass
class AgentRiskState:
    """Per-agent risk state, persisted across runs."""
    agent: str
    frozen: bool = False
    frozen_reason: str = ""
    frozen_since: str = ""
    last_equity: float = 0.0
    peak_equity: float = 0.0
    drawdown_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "frozen": self.frozen,
            "frozen_reason": self.frozen_reason,
            "frozen_since": self.frozen_since,
            "last_equity": round(self.last_equity, 4),
            "peak_equity": round(self.peak_equity, 4),
            "drawdown_pct": round(self.drawdown_pct, 3),
        }


@dataclass
class SystemRiskState:
    """System-wide risk state."""
    safe_mode: bool = False
    safe_mode_reason: str = ""
    safe_mode_since: str = ""
    cohort_avg_return_pct: float = 0.0
    cohort_history: List[Dict[str, Any]] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Evaluation
# ─────────────────────────────────────────────────────────────────

def evaluate_agent_risk(
    agent_state: AgentRiskState,
    current_equity: float,
    weight_multiplier: Optional[float],
    scored_calls: int,
    today_iso: str,
    config: Dict[str, Any] = None,
) -> Tuple[AgentRiskState, str]:
    """
    Evaluate one agent's risk state for today.
    Returns (updated_state, action_log) where action_log is a string
    describing any state transition that happened.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    log_msg = ""

    # Update peak/last equity
    if current_equity > agent_state.peak_equity:
        agent_state.peak_equity = current_equity
    if agent_state.last_equity == 0:
        agent_state.last_equity = current_equity

    # Compute current drawdown from peak
    dd = 0.0
    if agent_state.peak_equity > 0:
        dd = (agent_state.peak_equity - current_equity) / agent_state.peak_equity
    agent_state.drawdown_pct = dd

    # Daily move (last_equity → current_equity)
    if agent_state.last_equity > 0:
        daily_move = (current_equity - agent_state.last_equity) / agent_state.last_equity
    else:
        daily_move = 0.0

    # ── Freeze conditions ────────────────────────────────────
    if not agent_state.frozen:
        # Daily drawdown trigger
        if daily_move <= -cfg["daily_drawdown_freeze_pct"]:
            agent_state.frozen = True
            agent_state.frozen_reason = (
                f"Daily drawdown of {daily_move*100:+.2f}% exceeded "
                f"{-cfg['daily_drawdown_freeze_pct']*100:.0f}% threshold. "
                f"Frozen until rebound."
            )
            agent_state.frozen_since = today_iso
            log_msg = f"FROZEN ({agent_state.agent}): daily DD"

        # Track-record kill switch
        elif (weight_multiplier is not None
              and weight_multiplier < cfg["kill_weight_threshold"]
              and scored_calls >= cfg["kill_min_calls"]):
            agent_state.frozen = True
            agent_state.frozen_reason = (
                f"Performance below baseline: weight multiplier "
                f"{weight_multiplier:.2f}× < {cfg['kill_weight_threshold']:.2f}× "
                f"(after {scored_calls} scored calls). Frozen until track record recovers."
            )
            agent_state.frozen_since = today_iso
            log_msg = f"FROZEN ({agent_state.agent}): track record"

    # ── Unfreeze conditions ──────────────────────────────────
    elif agent_state.frozen:
        # Performance kill switch recovery
        weight_recovered = (weight_multiplier is None
                          or weight_multiplier >= cfg["kill_weight_threshold"])
        # Drawdown rebound
        rebound_ok = daily_move >= cfg["daily_drawdown_unfreeze_pct"]

        if weight_recovered and (rebound_ok or "Daily drawdown" not in agent_state.frozen_reason):
            agent_state.frozen = False
            agent_state.frozen_reason = ""
            agent_state.frozen_since = ""
            log_msg = f"UNFROZEN ({agent_state.agent}): conditions cleared"

    agent_state.last_equity = current_equity
    return agent_state, log_msg


def evaluate_cohort_risk(
    system_state: SystemRiskState,
    portfolio_returns_pct: List[float],
    today_iso: str,
    config: Dict[str, Any] = None,
) -> Tuple[SystemRiskState, str]:
    """
    Evaluate whether the entire cohort has cratered enough to trip
    the system-wide SAFE MODE kill switch.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}

    if not portfolio_returns_pct:
        return system_state, ""

    avg_ret = sum(portfolio_returns_pct) / len(portfolio_returns_pct)
    system_state.cohort_avg_return_pct = avg_ret

    # Append to rolling history
    system_state.cohort_history.append({
        "date": today_iso,
        "cohort_avg_return_pct": round(avg_ret, 3),
        "n_agents": len(portfolio_returns_pct),
    })
    system_state.cohort_history = system_state.cohort_history[-180:]  # 6 months

    log_msg = ""
    if not system_state.safe_mode:
        if (len(system_state.cohort_history) >= cfg["cohort_dd_min_runs"]
            and avg_ret <= -cfg["cohort_dd_threshold"] * 100):
            system_state.safe_mode = True
            system_state.safe_mode_reason = (
                f"Cohort average return {avg_ret:+.2f}% breached "
                f"−{cfg['cohort_dd_threshold']*100:.0f}% safe-mode threshold. "
                f"All agents holding existing positions; no new opens."
            )
            system_state.safe_mode_since = today_iso
            log_msg = "SYSTEM ENTERING SAFE MODE"
    else:
        if avg_ret > -cfg["cohort_dd_threshold"] * 50:  # need to recover halfway
            system_state.safe_mode = False
            system_state.safe_mode_reason = ""
            system_state.safe_mode_since = ""
            log_msg = "SYSTEM EXITING SAFE MODE"

    return system_state, log_msg


# ─────────────────────────────────────────────────────────────────
# Plan-level filtering
# ─────────────────────────────────────────────────────────────────

def filter_plans_by_risk(
    plans: List[Dict[str, Any]],
    config: Dict[str, Any] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Apply plan-level risk filters. Returns (kept, rejected).
    Each rejected plan gets a `rejected_reason` field.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    kept, rejected = [], []
    for p in plans:
        rr = p.get("reward_risk_ratio", 0)
        risk_pct = p.get("risk_pct_of_portfolio", 0)
        if rr < cfg["min_reward_risk"]:
            rejected.append({
                **p,
                "rejected_reason": (
                    f"Reward/risk {rr:.2f}:1 below minimum {cfg['min_reward_risk']:.1f}:1"
                ),
            })
            continue
        if risk_pct > cfg["max_risk_per_plan_pct"]:
            rejected.append({
                **p,
                "rejected_reason": (
                    f"Risk {risk_pct*100:.2f}% above per-plan cap "
                    f"{cfg['max_risk_per_plan_pct']*100:.0f}%"
                ),
            })
            continue
        kept.append(p)
    return kept, rejected


# ─────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────

def load_risk_state(path: Path) -> Tuple[Dict[str, AgentRiskState], SystemRiskState]:
    """Load both per-agent and system risk state."""
    if not path.exists():
        return {}, SystemRiskState()
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}, SystemRiskState()

    agents = {}
    for name, payload in data.get("agents", {}).items():
        agents[name] = AgentRiskState(
            agent=name,
            frozen=payload.get("frozen", False),
            frozen_reason=payload.get("frozen_reason", ""),
            frozen_since=payload.get("frozen_since", ""),
            last_equity=payload.get("last_equity", 0.0),
            peak_equity=payload.get("peak_equity", 0.0),
            drawdown_pct=payload.get("drawdown_pct", 0.0),
        )
    sysd = data.get("system", {})
    system = SystemRiskState(
        safe_mode=sysd.get("safe_mode", False),
        safe_mode_reason=sysd.get("safe_mode_reason", ""),
        safe_mode_since=sysd.get("safe_mode_since", ""),
        cohort_avg_return_pct=sysd.get("cohort_avg_return_pct", 0.0),
        cohort_history=sysd.get("cohort_history", []),
    )
    return agents, system


def save_risk_state(
    path: Path,
    agents: Dict[str, AgentRiskState],
    system: SystemRiskState,
    config: Dict[str, Any],
) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "system": {
            "safe_mode": system.safe_mode,
            "safe_mode_reason": system.safe_mode_reason,
            "safe_mode_since": system.safe_mode_since,
            "cohort_avg_return_pct": round(system.cohort_avg_return_pct, 3),
            "cohort_history": system.cohort_history,
        },
        "agents": {name: a.to_dict() for name, a in agents.items()},
        "summary": {
            "frozen_count": sum(1 for a in agents.values() if a.frozen),
            "total_count": len(agents),
            "safe_mode": system.safe_mode,
        },
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
