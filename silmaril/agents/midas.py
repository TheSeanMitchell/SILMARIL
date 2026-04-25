"""
silmaril.agents.midas — King Midas, sovereign of hard currencies.

Midas trades only metals and reserve currencies. No stocks. No bonds. No
crypto. A parallel $1 compounder running alongside SCROOGE with a different
universe and a different temperament.

SCROOGE chases whatever the team ranks highest. MIDAS believes only in
things that have been wealth for thousands of years:
  - Gold, silver, platinum, palladium
  - The US dollar, euro, yen, Swiss franc

Where SCROOGE is volatile, MIDAS is patient. His edge is not a clever
setup; it is refusing to trade anything that wasn't wealth when
kingdoms rose and fell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .base import Agent, AssetContext, Signal, Verdict
from ..execution.detail import build_execution


# ─────────────────────────────────────────────────────────────────
# Midas's universe — what he will and will not own
# ─────────────────────────────────────────────────────────────────

MIDAS_UNIVERSE: Dict[str, str] = {
    # Precious metals
    "GLD":  "Gold (SPDR)",
    "IAU":  "Gold (iShares)",
    "SLV":  "Silver (iShares)",
    "SIVR": "Silver (Aberdeen)",
    "PPLT": "Platinum (Aberdeen)",
    "PALL": "Palladium (Aberdeen)",
    # Hard currencies — reserve status, deep liquidity, historical store of value
    "UUP":  "US Dollar Index",
    "FXE":  "Euro",
    "FXY":  "Japanese Yen",
    "FXF":  "Swiss Franc",
}


# ─────────────────────────────────────────────────────────────────
# The agent
# ─────────────────────────────────────────────────────────────────

class Midas(Agent):
    codename = "MIDAS"
    specialty = "Hard Currency & Precious Metals"
    temperament = "Ancient sovereign. Keeps his wealth only in things that have always been wealth."
    inspiration = "King Midas — patient accumulation, the golden touch"
    asset_classes = ("etf",)

    def applies_to(self, ctx: AssetContext) -> bool:
        return ctx.ticker.upper() in MIDAS_UNIVERSE

    def _judge(self, ctx: AssetContext) -> Verdict:
        if not ctx.price or not ctx.sma_50 or not ctx.sma_200:
            return self._hold(ctx, "awaiting full trend data — Midas is patient")

        above_200 = ctx.price > ctx.sma_200
        above_50 = ctx.price > ctx.sma_50
        rsi = ctx.rsi_14 or 50

        # Strong setup: hard asset in uptrend, not yet overbought
        if above_200 and above_50 and rsi < 70:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.65,
                rationale=(
                    f"Hard asset in uptrend, RSI {rsi:.0f} — "
                    f"still gold worth accumulating."
                ),
                factors={"above_sma200": True, "rsi": round(rsi, 1)},
                suggested_entry=round(ctx.price, 2),
                suggested_stop=round(ctx.sma_200, 2),
                suggested_target=round(ctx.price * 1.15, 2),
                invalidation="Close below SMA-200 breaks the sovereign thesis.",
            )

        # Mildly overbought — hold, don't chase
        if rsi >= 70:
            return self._hold(ctx, f"RSI {rsi:.0f} overbought — Midas waits")

        # Below trend — rare, but patient kings buy fear
        if not above_200 and rsi < 40:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.55,
                rationale="Below trend with fear — Midas accumulates when kingdoms falter.",
                factors={"below_sma200": True, "rsi": round(rsi, 1)},
                suggested_entry=round(ctx.price, 2),
                suggested_stop=round(ctx.price * 0.92, 2),
                suggested_target=round(ctx.sma_200, 2),
            )

        return self._hold(ctx, "mixed structure — Midas stands still")

    def _hold(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.HOLD, conviction=0.4, rationale=reason,
        )


midas = Midas()


# ─────────────────────────────────────────────────────────────────
# MIDAS as $1 parallel compounder — state + action function
# ─────────────────────────────────────────────────────────────────

@dataclass
class MidasState:
    balance: float = 1.0
    current_position: Optional[Dict] = None
    lifetime_peak: float = 1.0
    current_life: int = 1
    life_start_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat()
    )
    history: List[Dict] = field(default_factory=list)
    deaths: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "codename": "MIDAS",
            "style": "hard-currency compounder",
            "inspiration": "King Midas",
            "balance": round(self.balance, 4),
            "current_position": self.current_position,
            "lifetime_peak": round(self.lifetime_peak, 4),
            "current_life": self.current_life,
            "life_start_date": self.life_start_date,
            "actions_this_life": len(self.history),
            "history": self.history[-30:],
            "deaths": self.deaths,
            "universe": list(MIDAS_UNIVERSE.keys()),
        }


def midas_act(
    state: MidasState,
    debates: List[Dict],
    prices: Dict[str, float],
) -> MidasState:
    """Midas picks the highest-consensus hard-currency BUY. Otherwise holds."""
    today = datetime.now(timezone.utc).date().isoformat()

    # ── First, mark-to-market any existing position ─────────────
    if state.current_position:
        ticker = state.current_position["ticker"]
        current_price = prices.get(ticker)
        if current_price:
            shares = state.current_position["shares"]
            state.balance = round(shares * current_price, 4)
            state.lifetime_peak = max(state.lifetime_peak, state.balance)

    # ── Find candidates in Midas's universe ─────────────────────
    candidates = [
        d for d in debates
        if d.get("ticker", "").upper() in MIDAS_UNIVERSE
        and d.get("consensus", {}).get("signal") in ("BUY", "STRONG_BUY")
    ]
    if not candidates:
        return state  # hold current position; no new rotation

    candidates.sort(
        key=lambda d: (
            d["consensus"]["score"],
            d["consensus"]["avg_conviction"],
        ),
        reverse=True,
    )
    target = candidates[0]
    target_ticker = target["ticker"]
    target_price = prices.get(target_ticker)
    if not target_price:
        return state

    # ── If already holding the target, nothing to do ────────────
    if state.current_position and state.current_position["ticker"] == target_ticker:
        return state

    # ── Rotate: sell old, buy new ───────────────────────────────
    if state.current_position:
        old_tkr = state.current_position["ticker"]
        old_shares = state.current_position["shares"]
        old_entry = state.current_position["entry_price"]
        old_current = prices.get(old_tkr, old_entry)
        execution = build_execution(
            ticker=old_tkr, asset_class="etf", side="SELL",
            shares=old_shares, price=old_current, available_before=0.0,
        )
        proceeds = execution["net_proceeds"] or (old_shares * old_current)
        state.history.append({
            "date": today,
            "action": "SELL",
            "ticker": old_tkr,
            "shares": round(old_shares, 6),
            "price": round(old_current, 4),
            "proceeds": round(proceeds, 4),
            "pnl_pct": round(((old_current / old_entry) - 1) * 100, 2),
            "execution": execution,
        })
        state.balance = round(proceeds, 4)

    # Midas's wealth doesn't die — metals don't go to zero — but just in case
    if state.balance <= 0:
        state.deaths.append({
            "life": state.current_life,
            "ended": today,
            "peak": state.lifetime_peak,
        })
        state.current_life += 1
        state.balance = 1.0
        state.life_start_date = today
        state.history = []

    # Account for buy-side fees when sizing
    available = state.balance
    shares = available / target_price
    for _ in range(3):
        test_exec = build_execution(
            ticker=target_ticker, asset_class="etf", side="BUY",
            shares=shares, price=target_price, available_before=available,
        )
        over = (test_exec["net_cost"] or 0) - available
        if over <= 0.0001:
            break
        shares -= (over / target_price) * 1.01
    execution = build_execution(
        ticker=target_ticker, asset_class="etf", side="BUY",
        shares=shares, price=target_price, available_before=available,
    )

    state.current_position = {
        "ticker": target_ticker,
        "name": MIDAS_UNIVERSE.get(target_ticker, target_ticker),
        "shares": round(shares, 6),
        "entry_price": round(target_price, 4),
        "entry_date": today,
        "thesis": (
            f"Consensus {target['consensus']['signal']} on hard asset "
            f"({MIDAS_UNIVERSE.get(target_ticker)}) — Midas accumulates."
        ),
        "execution": execution,
    }
    state.history.append({
        "date": today,
        "action": "BUY",
        "ticker": target_ticker,
        "shares": round(shares, 6),
        "price": round(target_price, 4),
        "cost": round(state.balance, 4),
        "execution": execution,
    })
    state.lifetime_peak = max(state.lifetime_peak, state.balance)
    return state
