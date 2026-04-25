"""
silmaril.trade_engine.plans — Build full trade plans from debate output.

A trade plan is the difference between a signal and an actionable idea.
A raw "BUY AAPL" is not tradeable. SILMARIL gives you:

    BUY AAPL @ $180.22
    Stop:   $174.85  (–2.98%,  1.5 ATR)
    Target: $189.40  (+5.09%, 2.5:1 reward/risk)
    Size:   65 shares ($11,714 position; 2.0% portfolio risk)
    Invalidation: Close below $174.85 OR QQQ breaks SMA50
    Backers:  FORGE (0.78), ZENITH (0.62), VEIL (0.55)
    Dissent:  AEGIS (0.65) — VIX elevated; wait for pullback

Every plan preserves the reasoning. Nothing is a black box.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


DEFAULT_PORTFOLIO_SIZE = 10_000.0       # per-agent starting capital
DEFAULT_RISK_PER_TRADE = 0.02           # 2% of portfolio per trade
MIN_REWARD_RISK = 1.5                   # refuse plans worse than 1.5:1


@dataclass
class TradePlan:
    """A fully-specified, simulated trade plan."""
    plan_id: str
    ticker: str
    name: str
    direction: str                  # "LONG" | "SHORT"
    entry: float
    stop: float
    target: float
    shares: float
    position_value: float
    risk_amount: float              # dollars at risk (entry - stop) * shares
    risk_pct_of_portfolio: float
    reward_risk_ratio: float
    invalidation: str
    backers: List[Dict[str, Any]] = field(default_factory=list)
    dissenters: List[Dict[str, Any]] = field(default_factory=list)
    consensus_signal: str = "BUY"
    portfolio_size: float = DEFAULT_PORTFOLIO_SIZE
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "ACTIVE"          # ACTIVE | FILLED | STOPPED | TARGET_HIT | EXPIRED
    execution: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "ticker": self.ticker,
            "name": self.name,
            "direction": self.direction,
            "entry": round(self.entry, 2),
            "stop": round(self.stop, 2),
            "target": round(self.target, 2),
            "shares": round(self.shares, 4),
            "position_value": round(self.position_value, 2),
            "risk_amount": round(self.risk_amount, 2),
            "risk_pct_of_portfolio": round(self.risk_pct_of_portfolio, 4),
            "reward_risk_ratio": round(self.reward_risk_ratio, 2),
            "invalidation": self.invalidation,
            "backers": self.backers,
            "dissenters": self.dissenters,
            "consensus_signal": self.consensus_signal,
            "portfolio_size": self.portfolio_size,
            "generated_at": self.generated_at.isoformat(),
            "status": self.status,
            "execution": self.execution,
        }


def build_plan_from_debate(
    debate: Dict[str, Any],
    portfolio_size: float = DEFAULT_PORTFOLIO_SIZE,
    risk_per_trade: float = DEFAULT_RISK_PER_TRADE,
) -> Optional[TradePlan]:
    """
    Translate one debate into a trade plan (or None if not actionable).

    Only BUY/STRONG_BUY consensus produces LONG plans. AEGIS vetoes
    already-downgraded-to-HOLD debates in the arbiter, so a vetoed
    asset will not reach here with a BUY consensus.
    """
    consensus = debate["consensus"]
    if consensus["signal"] not in ("BUY", "STRONG_BUY"):
        return None

    price = debate.get("price")
    if not price or price <= 0:
        return None

    # ── Aggregate backers' suggested entries/stops/targets ──────
    voting = [
        v for v in debate.get("verdicts", [])
        if v["signal"] in ("BUY", "STRONG_BUY")
        and v.get("suggested_entry")
        and v.get("suggested_stop")
        and v.get("suggested_target")
    ]

    if not voting:
        # No agent provided concrete levels — synthesize conservative ones
        # Tight, technical-anchor inspired levels
        entry = price
        stop = price * 0.97          # 3% stop
        target = price * 1.045       # 4.5% target (1.5:1)
    else:
        # Conviction-weighted averaging across backers
        total_w = sum(v["conviction"] for v in voting) or 1.0
        entry = sum(v["suggested_entry"] * v["conviction"] for v in voting) / total_w
        stop = sum(v["suggested_stop"] * v["conviction"] for v in voting) / total_w
        target = sum(v["suggested_target"] * v["conviction"] for v in voting) / total_w

    # ── Realism cap: target cannot exceed +12% in any single plan ──
    # Prevents agents that suggested aggressive ATR multiples from producing
    # targets that require fresh all-time-highs. Real day-trading targets
    # rarely justify more than ~10% above entry.
    max_target_pct = 0.12
    if target > entry * (1 + max_target_pct):
        target = entry * (1 + max_target_pct)

    # ── Realism cap: stop cannot be tighter than 1.5% (fees + spread eat it) ──
    # And cannot be wider than 6% (then it's not a stop, it's a hope)
    min_stop_pct = 0.015
    max_stop_pct = 0.06
    if (entry - stop) / entry < min_stop_pct:
        stop = entry * (1 - min_stop_pct)
    if (entry - stop) / entry > max_stop_pct:
        stop = entry * (1 - max_stop_pct)

    # Sanity checks
    if stop >= entry or target <= entry:
        return None

    # Reward/risk
    risk_per_share = entry - stop
    reward_per_share = target - entry
    reward_risk = reward_per_share / risk_per_share if risk_per_share else 0
    if reward_risk < MIN_REWARD_RISK:
        return None

    # ── Position sizing ─────────────────────────────────────────
    dollars_at_risk = portfolio_size * risk_per_trade
    shares = dollars_at_risk / risk_per_share
    position_value = shares * entry

    # Cap position at 20% of portfolio regardless of risk math
    max_position = portfolio_size * 0.20
    if position_value > max_position:
        shares = max_position / entry
        position_value = shares * entry
        dollars_at_risk = shares * risk_per_share

    # ── Backers / dissenters ────────────────────────────────────
    all_verdicts = debate.get("verdicts", [])
    backers = [
        {
            "agent": v["agent"],
            "conviction": v["conviction"],
            "rationale": v["rationale"],
        }
        for v in all_verdicts
        if v["signal"] in ("BUY", "STRONG_BUY")
    ]
    dissenters = [
        {
            "agent": v["agent"],
            "signal": v["signal"],
            "conviction": v["conviction"],
            "rationale": v["rationale"],
        }
        for v in all_verdicts
        if v["signal"] in ("SELL", "STRONG_SELL")
    ]

    # ── Invalidation (prefer the strongest backer's phrasing) ───
    invalidation = None
    strongest_backer = max(voting, key=lambda v: v["conviction"], default=None)
    if strongest_backer and strongest_backer.get("invalidation"):
        invalidation = strongest_backer["invalidation"]
    else:
        invalidation = (
            f"Close below ${stop:.2f} invalidates the thesis. "
            f"Re-evaluate if consensus agreement drops below 50%."
        )

    plan_id = _gen_plan_id(debate["ticker"])

    # ── Execution metadata: what this would look like at a real broker ─
    from ..execution.detail import build_execution
    asset_class = debate.get("asset_class") or "equity"
    execution = build_execution(
        ticker=debate["ticker"],
        asset_class=asset_class,
        side="BUY",
        shares=shares,
        price=entry,
        available_before=portfolio_size,
    )

    return TradePlan(
        plan_id=plan_id,
        ticker=debate["ticker"],
        name=debate.get("name", debate["ticker"]),
        direction="LONG",
        entry=entry,
        stop=stop,
        target=target,
        shares=shares,
        position_value=position_value,
        risk_amount=dollars_at_risk,
        risk_pct_of_portfolio=dollars_at_risk / portfolio_size,
        reward_risk_ratio=reward_risk,
        invalidation=invalidation,
        backers=backers,
        dissenters=dissenters,
        consensus_signal=consensus["signal"],
        portfolio_size=portfolio_size,
        execution=execution,
    )


def _gen_plan_id(ticker: str) -> str:
    now = datetime.now(timezone.utc)
    return f"plan_{now.strftime('%Y%m%d_%H%M')}_{ticker.upper()}"
