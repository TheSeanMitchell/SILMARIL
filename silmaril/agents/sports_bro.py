"""
silmaril.agents.sports_bro — Sports Bro, prediction-market specialist.

Plays Polymarket and Kalshi only — never traditional sportsbooks.
The structural difference matters: peer-to-peer pricing on prediction
markets means tight spreads (~0.5–2%) vs traditional sportsbook vig
(~4.5%+). Edge is calculable; sportsbook edge is not.

Strategy: half-Kelly sizing on positive-EV opportunities only.
A $1 compounder. Combined balance, many small positions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .base import Agent, AssetContext, Signal, Verdict
from ..execution.detail import build_execution


MAX_TRADES_PER_DAY = 8
DEATH_THRESHOLD = 0.50
HALF_KELLY = 0.5


@dataclass
class SportsBroState:
    balance: float = 10.0
    open_bets: List[Dict] = field(default_factory=list)
    history: List[Dict] = field(default_factory=list)
    lifetime_peak: float = 10.0
    current_life: int = 1
    life_start_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat()
    )
    deaths: List[Dict] = field(default_factory=list)
    trades_today: int = 0
    last_action_date: str = ""

    def to_dict(self) -> Dict:
        return {
            "codename": "SPORTS_BRO",
            "title": "Prediction Market Trader",
            "balance": round(self.balance, 6),
            "open_bets": self.open_bets,
            "current_position": self.open_bets[0] if self.open_bets else None,
            "lifetime_peak": round(self.lifetime_peak, 6),
            "current_life": self.current_life,
            "life_start_date": self.life_start_date,
            "deaths": self.deaths,
            "trades_today": self.trades_today,
            "max_trades_per_day": MAX_TRADES_PER_DAY,
            "history": self.history[-30:],
            "actions_this_life": len(self.history),
            "days_alive": self._days_alive(),
        }

    def _days_alive(self) -> int:
        try:
            start = datetime.fromisoformat(self.life_start_date).date()
            today = datetime.now(timezone.utc).date()
            return max(0, (today - start).days)
        except Exception:
            return 0


class SportsBro(Agent):
    codename = "SPORTS_BRO"
    specialty = "Polymarket + Kalshi prediction markets"
    temperament = "Disciplined Kelly bettor, never traditional books"
    inspiration = "The arbitrageur who knows the vig and avoids it"
    asset_classes = ("prediction_market",)

    def applies_to(self, ctx: AssetContext) -> bool:
        return getattr(ctx, "asset_class", None) == "prediction_market"

    def _judge(self, ctx: AssetContext) -> Verdict:
        # Implied probability vs model probability decides edge
        market_prob = getattr(ctx, "market_prob", 0.5)
        model_prob = getattr(ctx, "model_prob", 0.5)
        edge = model_prob - market_prob
        if edge > 0.07:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=min(0.85, edge * 5),
                rationale=f"Model {model_prob:.0%} vs market {market_prob:.0%}. Edge +{edge*100:.0f} bps. Half-Kelly entry.",
            )
        if edge < -0.07:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=min(0.85, -edge * 5),
                rationale=f"Market overprices at {market_prob:.0%} vs model {model_prob:.0%}. Fade.",
            )
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.HOLD, conviction=0.4,
            rationale=f"No edge ({edge*100:+.1f} bps). Sports Bro doesn't bet without one.",
        )


sports_bro = SportsBro()


def _hours_until(deadline_iso: Optional[str]) -> Optional[float]:
    """Return hours from now until the given ISO deadline. None if invalid."""
    if not deadline_iso:
        return None
    try:
        # Handle both 'YYYY-MM-DD' and full ISO with time
        if "T" in deadline_iso:
            dl = datetime.fromisoformat(deadline_iso.replace("Z", "+00:00"))
        else:
            dl = datetime.fromisoformat(deadline_iso).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (dl - now).total_seconds() / 3600.0
    except Exception:
        return None


# v2.0: Sports Bro only takes positions on markets resolving within
# 48 hours so the user can actually see outcomes accumulate quickly.
# Markets with longer horizons (multi-month politics, year-end events)
# are filtered out — they tie up bankroll without producing data.
MAX_HOURS_TO_CLOSE = 48


def sports_bro_act(state: SportsBroState, candidates: List[Dict]) -> SportsBroState:
    today = datetime.now(timezone.utc).date().isoformat()
    if state.last_action_date != today:
        state.trades_today = 0
        state.last_action_date = today

    if state.balance < DEATH_THRESHOLD:
        state.deaths.append({
            "date": today, "life": state.current_life,
            "final_balance": round(state.balance, 6),
            "peak_balance": round(state.lifetime_peak, 6),
            "epitaph": f"Sports Bro busted on Life #{state.current_life}. Even with discipline, prediction markets are hard.",
        })
        state.balance = 10.0
        state.open_bets = []
        state.current_life += 1
        state.life_start_date = today
        state.lifetime_peak = 10.0
        state.trades_today = 0
        return state

    # Auto-settle bets whose deadline has passed.
    # Real-world settlement comes from venue resolution APIs. As a
    # transparent proxy: if the bet's deadline has passed, use the
    # current market_prob from `candidates` (matched by market name)
    # as the resolved truth. Above 0.50 → YES wins, below → NO wins.
    today_dt = datetime.now(timezone.utc).date()
    market_lookup = {c["market"]: c for c in candidates}
    new_open = []
    for bet in state.open_bets:
        deadline_iso = bet.get("deadline")
        if deadline_iso:
            try:
                deadline_dt = datetime.fromisoformat(deadline_iso).date()
            except Exception:
                deadline_dt = None
        else:
            deadline_dt = None
        is_expired = deadline_dt is not None and today_dt > deadline_dt
        explicit = bet.get("resolved")
        if not (is_expired or explicit):
            new_open.append(bet)
            continue
        # Resolve
        if explicit:
            won = bet.get("won", False)
            resolution_basis = "venue API"
        else:
            current = market_lookup.get(bet["market"])
            current_prob = current.get("market_prob", 0.5) if current else 0.5
            if bet.get("side", "YES") == "YES":
                won = current_prob >= 0.50
            else:
                won = current_prob < 0.50
            resolution_basis = f"deadline-passed proxy (mkt {current_prob:.0%})"
        # Payout: YES bet at price p pays 1/p multiplier of stake on win
        outcome_payout = (bet["stake"] * (1 / bet["entry_price"])) if won else 0
        pnl = outcome_payout - bet["stake"]
        state.balance += outcome_payout
        state.history.append({
            "date": today, "action": "SETTLE", "market": bet["market"],
            "venue": bet.get("venue", "Polymarket"),
            "stake": bet["stake"], "won": won, "pnl": round(pnl, 4),
            "balance_after": round(state.balance, 6),
            "resolution": resolution_basis,
        })
    state.open_bets = new_open
    state.lifetime_peak = max(state.lifetime_peak, state.balance)

    # Open new positions on top edge candidates that resolve within 48 hours
    short_horizon = []
    for c in candidates:
        hours = _hours_until(c.get("deadline"))
        if hours is not None and 0 < hours <= MAX_HOURS_TO_CLOSE:
            short_horizon.append(c)
    # Sort by edge descending so the best opportunities go first
    short_horizon.sort(key=lambda c: c.get("edge", 0), reverse=True)

    for c in short_horizon[:3]:
        if state.trades_today >= MAX_TRADES_PER_DAY:
            break
        edge = c.get("edge", 0)
        if edge < 0.07:
            continue
        kelly_frac = HALF_KELLY * edge / max(0.01, c.get("market_prob", 0.5) * (1 - c.get("market_prob", 0.5)))
        kelly_frac = max(0.0, min(0.10, kelly_frac))  # cap at 10% of book per bet
        stake = round(state.balance * kelly_frac, 4)
        if stake < 0.01:
            continue
        state.balance -= stake
        bet = {
            "date": today, "market": c["market"], "side": c.get("side", "YES"),
            "entry_price": c.get("market_prob", 0.5),
            "model_prob": c.get("model_prob", 0.5),
            "edge": edge, "stake": stake, "resolved": False, "won": False,
            "venue": c.get("venue", "Polymarket"),
        }
        state.open_bets.append(bet)
        state.history.append({
            "date": today, "action": "BUY", "market": c["market"],
            "stake": stake, "entry_price": c.get("market_prob"),
            "edge": edge, "venue": bet["venue"],
        })
        state.trades_today += 1
    return state
