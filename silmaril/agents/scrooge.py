"""
silmaril.agents.scrooge — The Saver.

SCROOGE is not a strategist. SCROOGE is a ceremony.

Every day, SCROOGE takes whatever he has and puts it entirely into the
single highest-consensus trade plan the debate produced. Next day he sells
and rolls it into the next. No diversification. No risk management.
Full conviction, every day, forever.

He starts with $10,000. If he loses 50%, the counter resets.
The pain of the reset is the lesson.

SCROOGE does not have his own _judge method because he does not evaluate
individual assets. He acts on the consensus output of the other agents.

Alpha 2.2: timestamps added to all history entries.
Alpha 2.3: daily guard (acts once per calendar day only),
           last_action_date persisted, starting capital $10,000.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import Agent, AssetContext, Signal, Verdict
from ..execution.detail import build_execution


STARTING_CAPITAL        = 10_000.00
REINCARNATION_THRESHOLD =  5_000.00


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ScroogeState:
    balance:          float = STARTING_CAPITAL
    current_position: Optional[Dict[str, Any]] = None
    lifetime_peak:    float = STARTING_CAPITAL
    current_life:     int   = 1
    life_start_date:  str   = field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat())
    history:          List[Dict[str, Any]] = field(default_factory=list)
    deaths:           List[Dict[str, Any]] = field(default_factory=list)
    last_action_date: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "balance":          round(self.balance, 4),
            "current_position": self.current_position,
            "lifetime_peak":    round(self.lifetime_peak, 4),
            "current_life":     self.current_life,
            "life_start_date":  self.life_start_date,
            "last_action_date": self.last_action_date,
            "days_alive":       self._days_alive(),
            "history":          self.history[-365:],
            "deaths":           self.deaths,
        }

    def _days_alive(self) -> int:
        start = datetime.fromisoformat(self.life_start_date)
        today = datetime.now(timezone.utc).date()
        return (today - start.date()).days if hasattr(start, "date") else (today - start).days


class Scrooge(Agent):
    codename      = "SCROOGE"
    specialty     = "The Dollar Compounder"
    temperament   = (
        "Parsimonious. Patient. Brutally compounded. One dollar at a time. "
        "When he dies, he is reborn. He has died many times before."
    )
    inspiration   = "The minimum viable trade, forever"
    asset_classes = ("equity", "etf", "crypto")

    def _judge(self, ctx: AssetContext) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0,
            rationale="SCROOGE does not vote; he only acts on consensus.",
        )


def scrooge_act(
    state: ScroogeState,
    top_consensus: List[Dict[str, Any]],
    prices: Dict[str, float],
    today: Optional[str] = None,
) -> ScroogeState:
    today = today or datetime.now(timezone.utc).date().isoformat()

    # ── Daily guard ───────────────────────────────────────────────
    if state.last_action_date == today:
        return state

    # ── Determine today's pick first (needed for rotation gate) ──
    next_pick = _pick_best_buy(top_consensus)

    # ── Fee-aware rotation gate ───────────────────────────────────
    if state.current_position and next_pick:
        held_ticker   = state.current_position["ticker"]
        target_ticker = next_pick["ticker"]
        target_price  = prices.get(target_ticker, 0)

        held_consensus = next(
            (c for c in top_consensus if c.get("ticker") == held_ticker), None)
        held_signal = held_consensus.get("signal", "HOLD") if held_consensus else "HOLD"
        held_score  = held_consensus.get("consensus_score", 0) if held_consensus else 0

        if held_ticker == target_ticker:
            state.last_action_date = today
            state.history.append({
                "date": today, "timestamp": _ts(),
                "action": "HODL", "ticker": held_ticker,
                "reason": "Top pick unchanged — hold, avoid fees.",
                "life": state.current_life,
            })
            return state

        try:
            from .fee_aware_rotation import should_rotate
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
                state.last_action_date = today
                state.history.append({
                    "date": today, "timestamp": _ts(),
                    "action": "HODL", "ticker": held_ticker,
                    "reason": why, "life": state.current_life,
                })
                return state
        except Exception as e:
            print(f"[scrooge] fee_aware_rotation skipped: {e}")

    # ── Close existing position ───────────────────────────────────
    if state.current_position:
        ticker      = state.current_position["ticker"]
        shares      = state.current_position["shares"]
        entry_price = state.current_position["entry_price"]
        exit_price  = prices.get(ticker)

        if exit_price is not None and exit_price > 0:
            asset_class = "crypto" if ticker.endswith("-USD") else "etf"
            try:
                execution = build_execution(
                    ticker=ticker, asset_class=asset_class, side="SELL",
                    shares=shares, price=exit_price, available_before=0.0,
                )
                realized = execution["net_proceeds"] or (shares * exit_price)
            except Exception:
                realized  = shares * exit_price
                execution = {}

            pnl_pct = (exit_price / entry_price - 1) * 100 if entry_price else 0.0
            state.history.append({
                "date": today, "timestamp": _ts(), "action": "SELL",
                "ticker": ticker, "shares": shares,
                "exit_price": round(exit_price, 4),
                "entry_price": round(entry_price, 4),
                "pnl": round(realized - state.balance, 4),
                "pnl_pct": round(pnl_pct, 2),
                "balance_after": round(realized, 4),
                "life": state.current_life, "execution": execution,
            })
            state.balance          = realized
            state.lifetime_peak    = max(state.lifetime_peak, realized)
            state.current_position = None
        else:
            state.history.append({
                "date": today, "timestamp": _ts(), "action": "HOLD",
                "ticker": ticker, "reason": "no closing price available",
                "life": state.current_life,
            })
            return state

    # ── Reincarnation check ───────────────────────────────────────
    if state.balance < REINCARNATION_THRESHOLD:
        state.deaths.append({
            "date": today, "life": state.current_life,
            "days_lived": state._days_alive(),
            "peak_balance": round(state.lifetime_peak, 4),
            "final_balance": round(state.balance, 4),
        })
        state.current_life    += 1
        state.life_start_date  = today
        state.balance          = STARTING_CAPITAL
        state.lifetime_peak    = STARTING_CAPITAL
        state.history.append({
            "date": today, "timestamp": _ts(),
            "action": "REINCARNATION", "life": state.current_life,
            "rationale": "Fell below 50% — SCROOGE begins again at $10K.",
        })

    # ── Pick today's play ─────────────────────────────────────────
    pick = _pick_best_buy(top_consensus)
    if not pick:
        state.last_action_date = today
        state.history.append({
            "date": today, "timestamp": _ts(), "action": "CASH",
            "reason": "no BUY-consensus assets today",
            "balance": round(state.balance, 4), "life": state.current_life,
        })
        return state

    ticker      = pick["ticker"]
    entry_price = prices.get(ticker)
    if not entry_price or entry_price <= 0:
        state.last_action_date = today
        state.history.append({
            "date": today, "timestamp": _ts(), "action": "CASH",
            "reason": f"no valid price for {ticker}",
            "balance": round(state.balance, 4), "life": state.current_life,
        })
        return state

    # ── Full allocation ───────────────────────────────────────────
    asset_class = "crypto" if ticker.endswith("-USD") else "etf"
    available   = state.balance
    shares      = available / entry_price
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
        "ticker": ticker, "shares": round(shares, 8),
        "entry_price": round(entry_price, 4), "entry_date": today,
        "thesis": pick.get("rationale", "highest consensus signal today"),
        "execution": execution,
    }
    state.last_action_date = today
    state.history.append({
        "date": today, "timestamp": _ts(), "action": "BUY",
        "ticker": ticker, "shares": round(shares, 8),
        "entry_price": round(entry_price, 4),
        "allocated": round(state.balance, 4),
        "life": state.current_life, "execution": execution,
    })
    return state


def _pick_best_buy(top_consensus: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates = [c for c in top_consensus if c.get("signal") in ("BUY", "STRONG_BUY")]
    if not candidates:
        return None
    candidates.sort(
        key=lambda c: (c.get("consensus_score", 0), c.get("avg_conviction", 0)),
        reverse=True,
    )
    return candidates[0]


scrooge = Scrooge()
