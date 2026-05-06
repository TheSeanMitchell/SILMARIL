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

v4.1 (PR 1B): timestamps added to every history entry (fixes 17:00 display bug).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import Agent, AssetContext, Signal, Verdict
from ..execution.detail import build_execution


STARTING_CAPITAL = 10.00  # $10 starting capital
REINCARNATION_THRESHOLD = 0.50  # Below $0.50 = reset


def _ts() -> str:
    """Current UTC timestamp as ISO string."""
    return datetime.now(timezone.utc).isoformat()


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
    last_action_date: str = ""
 
    def to_dict(self) -> Dict[str, Any]:
        return {
            "balance": round(self.balance, 4),
            "current_position": self.current_position,
            "lifetime_peak": round(self.lifetime_peak, 4),
            "current_life": self.current_life,
            "life_start_date": self.life_start_date,
            "last_action_date": self.last_action_date,
            "days_alive": self._days_alive(),
            "history": self.history[-365:],   # last year on disk
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
    """
    today = today or datetime.now(timezone.utc).date().isoformat()
 
    # ── Daily guard: SCROOGE acts once per calendar day only ─────
    # Without this, every 10-min run triggers a full sell+rebuy cycle.
    if state.last_action_date == today:
        return state  # Already acted today — hold current position
 
    # ── Determine today's pick FIRST so we can decide whether to rotate ─
    next_pick = _pick_best_buy(top_consensus)

    # ── Step 0: Fee-aware rotation gate ──────────────────────────
    if state.current_position and next_pick:
        try:
            from .fee_aware_rotation import should_rotate
            held_ticker = state.current_position["ticker"]
            target_ticker = next_pick["ticker"]
            target_price = prices.get(target_ticker, 0)

            held_consensus = next(
                (c for c in top_consensus if c.get("ticker") == held_ticker), None,
            )
            if held_consensus:
                held_signal = held_consensus.get("signal", "HOLD")
                held_score = held_consensus.get("consensus_score", 0)
            else:
                held_signal = "HOLD"
                held_score = 0

            if held_ticker == target_ticker:
                state.last_action_date = today   # mark as acted today
    state.history.append({
        "date": today, "timestamp": _ts(),
        "action": "BUY",
        "ticker": ticker,
        "shares": round(shares, 8),
        "entry_price": round(entry_price, 4),
        "allocated": round(state.balance, 4),
        "life": state.current_life,
        "execution": execution,
    })
 
    return state

            rotate, why = should_rotate(
                current_consensus_signal=held_signal,
                current_consensus_score=held_score,
                target_consensus_signal=next_pick.get("signal", "HOLD"),
                target_consensus_score=next_pick.get("consensus_score", 0),
                asset_class="crypto" if held_ticker.endswith("-USD") else "etf",
                price=target_price or 1.0,
                notional=state.balance,
                multiplier=2.0,
            )
            if not rotate:
                state.history.append({
                    "date": today, "timestamp": _ts(),
                    "action": "HODL",
                    "ticker": held_ticker,
                    "reason": why,
                    "life": state.current_life,
                })
                return state
        except Exception as e:
            # fee_aware_rotation unavailable or errored — proceed with rotation
            print(f"[scrooge] fee_aware_rotation skipped: {e}")

    # ── Step 1: Close yesterday's position, if any ──────────────
    if state.current_position:
        ticker = state.current_position["ticker"]
        shares = state.current_position["shares"]
        entry_price = state.current_position["entry_price"]
        exit_price = prices.get(ticker)

        if exit_price is not None and exit_price > 0:
            new_balance = shares * exit_price
            pnl_pct = (exit_price / entry_price - 1) * 100 if entry_price else 0.0

            asset_class = "crypto" if ticker.endswith("-USD") else "etf"
            try:
                execution = build_execution(
                    ticker=ticker, asset_class=asset_class, side="SELL",
                    shares=shares, price=exit_price,
                    available_before=0.0,
                )
                realized = execution["net_proceeds"] or new_balance
            except Exception:
                realized = new_balance
                execution = {}

            state.history.append({
                "date": today, "timestamp": _ts(),
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
                "date": today, "timestamp": _ts(),
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
            "date": today, "timestamp": _ts(),
            "action": "REINCARNATION",
            "life": state.current_life,
            "rationale": "Previous life ended below $0.50. SCROOGE begins again.",
        })

    # ── Step 3: Pick today's conviction play ────────────────────
    pick = _pick_best_buy(top_consensus)
    if not pick:
        state.history.append({
            "date": today, "timestamp": _ts(),
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
            "date": today, "timestamp": _ts(),
            "action": "CASH",
            "reason": f"no valid price available for {ticker}",
            "balance": round(state.balance, 4),
            "life": state.current_life,
        })
        return state

    # ── Step 4: Full allocation into the single best pick ───────
    asset_class = "crypto" if ticker.endswith("-USD") else "etf"
    available = state.balance
    shares = available / entry_price
    try:
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
    except Exception:
        execution = {}

    state.current_position = {
        "ticker": ticker,
        "shares": round(shares, 8),
        "entry_price": round(entry_price, 4),
        "entry_date": today,
        "thesis": pick.get("rationale", "highest consensus signal today"),
        "execution": execution,
    }

    state.history.append({
        "date": today, "timestamp": _ts(),
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
    candidates.sort(
        key=lambda c: (c.get("consensus_score", 0), c.get("avg_conviction", 0)),
        reverse=True,
    )
    return candidates[0]


scrooge = Scrooge()
