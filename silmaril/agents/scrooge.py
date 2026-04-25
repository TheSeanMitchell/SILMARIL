"""
silmaril.agents.scrooge — The Saver.

SCROOGE is not a strategist. SCROOGE is a ceremony.

Every day, SCROOGE takes whatever he has and puts it entirely into the
single highest-consensus trade plan the debate produced. Next day he sells
and rolls it into the next. No diversification. No risk management.
Full conviction, every day, forever.

He starts with $1. If he ever loses everything, the counter resets to $1
and we display the reset prominently. The pain of the reset is the lesson.

SCROOGE does not have his own _judge method because he does not evaluate
individual assets. He acts on the consensus output of the other fifteen
agents. His logic lives in silmaril.agents.scrooge.scrooge_act().

The $1 starting capital is the key: fractional shares are available for $1
minimums on Robinhood, Fidelity, and Cash App as of 2026. One dollar is
the genuine floor of retail participation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import Agent, AssetContext, Signal, Verdict
from ..execution.detail import build_execution


STARTING_CAPITAL = 1.00  # One US dollar. That's the whole idea.
REINCARNATION_THRESHOLD = 0.05  # Below $0.05 we call it a reset (rounding / fee realism)


@dataclass
class ScroogeState:
    """SCROOGE's full history. Persisted to scrooge.json."""
    balance: float = STARTING_CAPITAL
    current_position: Optional[Dict[str, Any]] = None   # {ticker, shares, entry_price, entry_date}
    lifetime_peak: float = STARTING_CAPITAL
    current_life: int = 1                               # incremented on every reincarnation
    life_start_date: str = field(default_factory=lambda: datetime.now(timezone.utc).date().isoformat())
    history: List[Dict[str, Any]] = field(default_factory=list)
    deaths: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "balance": round(self.balance, 4),
            "current_position": self.current_position,
            "lifetime_peak": round(self.lifetime_peak, 4),
            "current_life": self.current_life,
            "life_start_date": self.life_start_date,
            "days_alive": self._days_alive(),
            "history": self.history[-365:],   # last year on disk; keep storage finite
            "deaths": self.deaths,
        }

    def _days_alive(self) -> int:
        start = datetime.fromisoformat(self.life_start_date)
        today = datetime.now(timezone.utc).date()
        return (today - start.date()).days if hasattr(start, "date") else (today - start).days


class Scrooge(Agent):
    """Formal Agent subclass so SCROOGE shows up in the roster, but he
    does not vote in debates — only acts on their output."""
    codename = "SCROOGE"
    specialty = "The Dollar Compounder"
    temperament = (
        "Parsimonious. Patient. Brutally compounded. One dollar at a time. "
        "When he dies, he is reborn. He has died many times before."
    )
    inspiration = "The minimum viable trade, forever"
    asset_classes = ("equity", "etf", "crypto")

    def _judge(self, ctx: AssetContext) -> Verdict:
        """SCROOGE abstains from per-asset judgement. His action happens elsewhere."""
        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=Signal.ABSTAIN,
            conviction=0.0,
            rationale="SCROOGE does not vote; he only acts on consensus.",
        )


# ─────────────────────────────────────────────────────────────────
# SCROOGE's actual behavior: runs daily after the debate resolves
# ─────────────────────────────────────────────────────────────────

def scrooge_act(
    state: ScroogeState,
    top_consensus: List[Dict[str, Any]],
    prices: Dict[str, float],
    today: Optional[str] = None,
) -> ScroogeState:
    """
    Execute SCROOGE's daily routine:
      1. If he has a position, sell it at today's close and update balance
      2. Check for reincarnation (balance below threshold → reset to $1)
      3. Find today's highest-consensus BUY among top_consensus
      4. Put the entire balance into it (fractional shares allowed)
      5. Record everything to history

    Arguments:
      state:          SCROOGE's current state (mutated and returned)
      top_consensus:  list of debate entries sorted by consensus strength,
                      each {"ticker", "signal", "consensus_score", ...}
      prices:         ticker -> latest close price
      today:          ISO date string; defaults to UTC today
    """
    today = today or datetime.now(timezone.utc).date().isoformat()

    # ── Step 1: Close yesterday's position, if any ──────────────
    if state.current_position:
        ticker = state.current_position["ticker"]
        shares = state.current_position["shares"]
        entry_price = state.current_position["entry_price"]
        exit_price = prices.get(ticker)

        if exit_price is not None:
            new_balance = shares * exit_price
            pnl = new_balance - state.balance
            pnl_pct = (exit_price / entry_price - 1) * 100 if entry_price else 0.0

            asset_class = "crypto" if ticker.endswith("-USD") else "etf"
            execution = build_execution(
                ticker=ticker, asset_class=asset_class, side="SELL",
                shares=shares, price=exit_price,
                available_before=0.0,  # was all-in
            )
            # Realize the fee drag against the proceeds
            realized = execution["net_proceeds"] or new_balance

            state.history.append({
                "date": today,
                "action": "SELL",
                "ticker": ticker,
                "shares": shares,
                "exit_price": round(exit_price, 4),
                "entry_price": round(entry_price, 4),
                "pnl": round(realized - state.balance, 4),
                "pnl_pct": round(pnl_pct, 2),
                "balance_after": round(realized, 4),
                "life": state.current_life,
                "execution": execution,
            })

            state.balance = realized
            state.lifetime_peak = max(state.lifetime_peak, realized)
            state.current_position = None
        else:
            # Price unavailable — hold the position one more day
            state.history.append({
                "date": today,
                "action": "HOLD",
                "ticker": ticker,
                "reason": "no closing price available",
                "life": state.current_life,
            })
            return state

    # ── Step 2: Reincarnation check ─────────────────────────────
    if state.balance < REINCARNATION_THRESHOLD:
        state.deaths.append({
            "date": today,
            "life": state.current_life,
            "days_lived": state._days_alive(),
            "peak_balance": round(state.lifetime_peak, 4),
            "final_balance": round(state.balance, 4),
        })
        state.current_life += 1
        state.life_start_date = today
        state.balance = STARTING_CAPITAL
        state.lifetime_peak = STARTING_CAPITAL
        state.history.append({
            "date": today,
            "action": "REINCARNATION",
            "life": state.current_life,
            "rationale": "Previous life ended below $0.05. SCROOGE begins again with $1.",
        })

    # ── Step 3: Pick today's conviction play ────────────────────
    pick = _pick_best_buy(top_consensus)
    if not pick:
        state.history.append({
            "date": today,
            "action": "CASH",
            "reason": "no BUY-consensus assets today",
            "balance": round(state.balance, 4),
            "life": state.current_life,
        })
        return state

    ticker = pick["ticker"]
    entry_price = prices.get(ticker)
    if not entry_price or entry_price <= 0:
        state.history.append({
            "date": today,
            "action": "CASH",
            "reason": f"no price available for {ticker}",
            "balance": round(state.balance, 4),
            "life": state.current_life,
        })
        return state

    # ── Step 4: Full allocation into the single best pick ───────
    asset_class = "crypto" if ticker.endswith("-USD") else "etf"
    # Account for buy-side fees so we don't over-allocate
    available = state.balance
    # Rough pre-compute: we want shares such that shares*price + fees ≈ balance
    # Simple iterative fit (cheap because fees are tiny)
    shares = available / entry_price
    for _ in range(3):
        test_exec = build_execution(
            ticker=ticker, asset_class=asset_class, side="BUY",
            shares=shares, price=entry_price, available_before=available,
        )
        over = (test_exec["net_cost"] or 0) - available
        if over <= 0.0001:
            break
        shares -= (over / entry_price) * 1.01
    execution = build_execution(
        ticker=ticker, asset_class=asset_class, side="BUY",
        shares=shares, price=entry_price, available_before=available,
    )

    state.current_position = {
        "ticker": ticker,
        "shares": round(shares, 8),
        "entry_price": round(entry_price, 4),
        "entry_date": today,
        "thesis": pick.get("rationale", "highest consensus signal today"),
        "execution": execution,
    }

    state.history.append({
        "date": today,
        "action": "BUY",
        "ticker": ticker,
        "shares": round(shares, 8),
        "entry_price": round(entry_price, 4),
        "allocated": round(state.balance, 4),
        "life": state.current_life,
        "execution": execution,
    })

    return state


def _pick_best_buy(top_consensus: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick the single highest-consensus BUY or STRONG_BUY from the debate output."""
    candidates = [
        c for c in top_consensus
        if c.get("signal") in ("BUY", "STRONG_BUY")
    ]
    if not candidates:
        return None
    # Sort by consensus_score descending, then conviction
    candidates.sort(
        key=lambda c: (c.get("consensus_score", 0), c.get("avg_conviction", 0)),
        reverse=True,
    )
    return candidates[0]


scrooge = Scrooge()
