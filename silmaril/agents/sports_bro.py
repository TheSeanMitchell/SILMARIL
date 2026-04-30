"""
silmaril.agents.sports_bro — Prediction-markets compounder.

Per operator request: "always aim for bets that are the closest possible
they can bet on, and prefer timelines that are closest so we can at least
see him working."

Strategy:
  1. Filter to markets resolving within 72 hours
  2. If none, expand to 7 days (fallback)
  3. Within the window, prefer closest-resolving first
  4. Pick highest-edge bet by Sports Bro's per-sport priors

This is a $1 compounder that takes its current cash and rolls it into a
single closest-resolving bet each cycle. When it busts → reset to $1, the
pain is the lesson.

State: docs/data/sports_bro.json (PROTECTED)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from .base import Agent, AssetContext, Signal, Verdict


# Per-sport prior win-rate for Sports Bro's edge (rough; updates Bayesian)
SPORT_PRIORS = {
    "nba": 0.54, "nfl": 0.53, "mlb": 0.52, "nhl": 0.52,
    "epl": 0.52, "champions_league": 0.52,
    "tennis": 0.55, "mma": 0.51, "golf": 0.50,
    "default": 0.50,
}

CLOSEST_HOURS = 72      # primary window
FALLBACK_HOURS = 168    # 7 days
DEATH_THRESHOLD = 0.50  # below $0.50 → reincarnation
MAX_TRADES_PER_DAY = 8
STARTING_CAPITAL = 10.00


# ─────────────────────────────────────────────────────────────────
# State dataclass — what cli.py expects
# ─────────────────────────────────────────────────────────────────

@dataclass
class SportsBroState:
    """Persistent state for Sports Bro across runs."""
    balance: float = STARTING_CAPITAL
    open_bets: List[Dict] = field(default_factory=list)
    history: List[Dict] = field(default_factory=list)
    lifetime_peak: float = STARTING_CAPITAL
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
            "title": "The Prediction-Market Bettor",
            "balance": round(self.balance, 4),
            "open_bets": self.open_bets,
            "history": self.history[-50:],
            "lifetime_peak": round(self.lifetime_peak, 4),
            "current_life": self.current_life,
            "life_start_date": self.life_start_date,
            "days_alive": self._days_alive(),
            "deaths": self.deaths,
            "trades_today": self.trades_today,
            "max_trades_per_day": MAX_TRADES_PER_DAY,
            "actions_this_life": len(self.history),
            "current_position": self.open_bets[0] if self.open_bets else None,
        }

    def _days_alive(self) -> int:
        try:
            start = datetime.fromisoformat(self.life_start_date).date()
            today = datetime.now(timezone.utc).date()
            return max(0, (today - start).days)
        except Exception:
            return 0


# ─────────────────────────────────────────────────────────────────
# Market filtering helpers
# ─────────────────────────────────────────────────────────────────

def _hours_until(market: dict, now: datetime) -> Optional[float]:
    end = market.get("end_date") or market.get("end_time") or market.get("close_time")
    if not end:
        return None
    try:
        if isinstance(end, str):
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        else:
            end_dt = end
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
        return (end_dt - now).total_seconds() / 3600.0
    except Exception:
        return None


def filter_eligible_markets(markets: List[dict]) -> List[dict]:
    """
    Closest-resolving first. Try 72h, fall back to 7d, fall back to whatever
    exists (top 10 by closeness).
    """
    if not markets:
        return []
    now = datetime.now(timezone.utc)
    enriched = []
    for m in markets:
        h = _hours_until(m, now)
        if h is not None and h > 0.5:
            enriched.append((m, h))
    enriched.sort(key=lambda r: r[1])

    for cap in (CLOSEST_HOURS, FALLBACK_HOURS):
        windowed = [m for m, h in enriched if h <= cap]
        if windowed:
            return windowed[:25]

    return [m for m, _ in enriched[:10]]


def pick_best_bet(markets: List[dict]) -> Optional[dict]:
    """
    Score eligible markets by (per-sport prior × implied-EV) and pick the
    closest among the top-3.
    """
    if not markets:
        return None
    eligible = filter_eligible_markets(markets)
    if not eligible:
        return None

    now = datetime.now(timezone.utc)
    scored = []
    for m in eligible:
        sport = (m.get("sport") or "default").lower()
        prior = SPORT_PRIORS.get(sport, SPORT_PRIORS["default"])
        price = m.get("price") or m.get("yes_price") or m.get("odds")
        if not price:
            continue
        try:
            price = float(price)
        except Exception:
            continue
        if 0 < price < 1:
            implied_p = price
        elif price > 1:
            implied_p = 1.0 / price
        else:
            continue
        edge = prior - implied_p
        if edge <= 0:
            continue
        h = _hours_until(m, now) or 999
        recency_bonus = 1.0 + max(0, (CLOSEST_HOURS - h) / CLOSEST_HOURS)
        scored.append((m, edge * recency_bonus, h))

    if not scored:
        return None
    scored.sort(key=lambda r: -r[1])
    top3 = scored[:3]
    top3.sort(key=lambda r: r[2])
    return top3[0][0]


def compose_bet(state: SportsBroState, market: dict) -> dict:
    """Stake the entire current bankroll on this single bet."""
    return {
        "market_id": market.get("id") or market.get("market_id"),
        "sport": market.get("sport"),
        "label": market.get("label") or market.get("title"),
        "side": market.get("recommended_side") or "YES",
        "stake": state.balance,
        "odds": market.get("price") or market.get("odds"),
        "ends": market.get("end_date") or market.get("end_time"),
        "placed_at": datetime.now(timezone.utc).isoformat(),
    }


def settle_active_bet(state: SportsBroState, won: bool, payout_multiplier: float = 2.0) -> SportsBroState:
    """Resolve the oldest open bet. If won, multiply by payout. If lost, reset to starting capital."""
    if not state.open_bets:
        return state
    bet = state.open_bets.pop(0)
    today = datetime.now(timezone.utc).date().isoformat()
    if won:
        new_bankroll = float(bet.get("stake", STARTING_CAPITAL)) * payout_multiplier
    else:
        new_bankroll = STARTING_CAPITAL
        state.deaths.append({
            "life": state.current_life,
            "ended": today,
            "peak": state.lifetime_peak,
        })
        state.current_life += 1
        state.life_start_date = today
    state.history.append({
        **bet,
        "won": won,
        "settled_at": datetime.now(timezone.utc).isoformat(),
        "new_bankroll": new_bankroll,
    })
    state.balance = new_bankroll
    state.lifetime_peak = max(state.lifetime_peak, state.balance)
    return state


# ─────────────────────────────────────────────────────────────────
# Action function — called by cli.py each cycle
# ─────────────────────────────────────────────────────────────────

def sports_bro_act(state: SportsBroState, markets: List[dict]) -> SportsBroState:
    """
    Sports Bro places (or holds) one bet per cycle on the closest-resolving
    eligible prediction market.
    """
    today = datetime.now(timezone.utc).date().isoformat()

    # Reset daily counter on new day
    if state.last_action_date != today:
        state.trades_today = 0
        state.last_action_date = today

    # Death check
    if state.balance < DEATH_THRESHOLD and not state.open_bets:
        state.deaths.append({
            "date": today,
            "life": state.current_life,
            "final_balance": round(state.balance, 4),
            "peak_balance": round(state.lifetime_peak, 4),
            "epitaph": (
                f"Sports Bro went bust on Life #{state.current_life}. "
                f"Peaked at ${state.lifetime_peak:.4f}."
            ),
        })
        state.balance = STARTING_CAPITAL
        state.current_life += 1
        state.life_start_date = today
        state.lifetime_peak = STARTING_CAPITAL
        state.trades_today = 0
        state.history.append({
            "date": today,
            "action": "REINCARNATION",
            "life": state.current_life,
        })

    # Cap daily trades
    if state.trades_today >= MAX_TRADES_PER_DAY:
        state.history.append({
            "date": today,
            "action": "HOLD",
            "reason": f"Daily trade cap ({MAX_TRADES_PER_DAY}) reached.",
            "balance": round(state.balance, 4),
        })
        return state

    # If already holding an open bet, don't stack another
    if state.open_bets:
        state.history.append({
            "date": today,
            "action": "HOLD",
            "reason": "Open bet still pending resolution.",
            "balance": round(state.balance, 4),
        })
        return state

    # Find the best market
    best = pick_best_bet(markets)
    if not best:
        state.history.append({
            "date": today,
            "action": "NO_BET",
            "reason": "No eligible markets with positive edge found.",
            "balance": round(state.balance, 4),
        })
        return state

    bet = compose_bet(state, best)
    state.open_bets.append(bet)
    state.trades_today += 1
    state.history.append({
        "date": today,
        "action": "BET",
        "market": bet.get("label"),
        "sport": bet.get("sport"),
        "side": bet.get("side"),
        "stake": round(state.balance, 4),
        "odds": bet.get("odds"),
        "ends": bet.get("ends"),
        "life": state.current_life,
    })
    return state


# ─────────────────────────────────────────────────────────────────
# Agent class + singleton — required by cli.py imports
# ─────────────────────────────────────────────────────────────────

class SportsBro(Agent):
    """Sports Bro as a voting agent (abstains on financial assets;
    his action happens via sports_bro_act on prediction markets)."""

    codename = "SPORTS_BRO"
    specialty = "Prediction Markets"
    temperament = (
        "Half-Kelly on the closest-resolving bet. Never sportsbooks. "
        "Polymarket + Kalshi only. Lives for the 72-hour window."
    )
    inspiration = "The Avengers prop-bet guy"
    asset_classes = ("equity", "etf", "crypto")  # needed so applies_to works

    def applies_to(self, ctx: AssetContext) -> bool:
        # Sports Bro never votes in the stock/crypto debate
        return False

    def _judge(self, ctx: AssetContext) -> Verdict:
        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=Signal.ABSTAIN,
            conviction=0.0,
            rationale="Sports Bro only bets on prediction markets, not financial assets.",
        )


sports_bro = SportsBro()
