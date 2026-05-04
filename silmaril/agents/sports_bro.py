"""silmaril.agents.sports_bro — Prediction-markets compounder. v2 with settle_expired_bets."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from .base import Agent, AssetContext, Signal, Verdict

SPORT_PRIORS = {
    "nba": 0.54, "nfl": 0.53, "mlb": 0.52, "nhl": 0.52,
    "epl": 0.52, "champions_league": 0.52,
    "tennis": 0.55, "mma": 0.51, "golf": 0.50, "default": 0.50,
}
CLOSEST_HOURS = 72
FALLBACK_HOURS = 168
DEATH_THRESHOLD = 0.50
MAX_TRADES_PER_DAY = 8
STARTING_CAPITAL = 10.00


@dataclass
class SportsBroState:
    balance: float = STARTING_CAPITAL
    open_bets: List[Dict] = field(default_factory=list)
    history: List[Dict] = field(default_factory=list)
    lifetime_peak: float = STARTING_CAPITAL
    current_life: int = 1
    life_start_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat())
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
            return max(0, (datetime.now(timezone.utc).date() - start).days)
        except Exception:
            return 0


def _hours_until(market: dict, now: datetime) -> Optional[float]:
    end = market.get("end_date") or market.get("end_time") or market.get("close_time")
    if not end: return None
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
    if not markets: return []
    now = datetime.now(timezone.utc)
    enriched = []
    for m in markets:
        h = _hours_until(m, now)
        if h is not None and h > 0.5:
            enriched.append((m, h))
    enriched.sort(key=lambda r: r[1])
    for cap in (CLOSEST_HOURS, FALLBACK_HOURS):
        windowed = [m for m, h in enriched if h <= cap]
        if windowed: return windowed[:25]
    return [m for m, _ in enriched[:10]]


def pick_best_bet(markets: List[dict]) -> Optional[dict]:
    if not markets: return None
    eligible = filter_eligible_markets(markets)
    if not eligible: return None
    now = datetime.now(timezone.utc)
    scored = []
    for m in eligible:
        sport = (m.get("sport") or "default").lower()
        prior = SPORT_PRIORS.get(sport, SPORT_PRIORS["default"])
        price = m.get("price") or m.get("yes_price") or m.get("odds")
        if not price: continue
        try: price = float(price)
        except Exception: continue
        if 0 < price < 1: implied_p = price
        elif price > 1: implied_p = 1.0 / price
        else: continue
        edge = prior - implied_p
        if edge <= 0: continue
        h = _hours_until(m, now) or 999
        recency_bonus = 1.0 + max(0, (CLOSEST_HOURS - h) / CLOSEST_HOURS)
        scored.append((m, edge * recency_bonus, h))
    if not scored: return None
    scored.sort(key=lambda r: -r[1])
    top3 = scored[:3]
    top3.sort(key=lambda r: r[2])
    return top3[0][0]


def compose_bet(state: SportsBroState, market: dict) -> dict:
    return {
        "market_id": market.get("id") or market.get("market_id"),
        "sport": market.get("sport"),
        "label": market.get("label") or market.get("title") or market.get("market"),
        "side": market.get("recommended_side") or "YES",
        "stake": state.balance,
        "odds": market.get("price") or market.get("odds"),
        "model_prob": market.get("model_prob"),
        "market_prob": market.get("market_prob") or market.get("price") or market.get("yes_price"),
        "ends": market.get("end_date") or market.get("end_time"),
        "end_date": market.get("end_date") or market.get("end_time"),
        "placed_at": datetime.now(timezone.utc).isoformat(),
    }


def settle_active_bet(state: SportsBroState, won: bool, payout_multiplier: float = 2.0) -> SportsBroState:
    if not state.open_bets: return state
    bet = state.open_bets.pop(0)
    today = datetime.now(timezone.utc).date().isoformat()
    if won:
        new_bankroll = float(bet.get("stake", STARTING_CAPITAL)) * payout_multiplier
    else:
        new_bankroll = STARTING_CAPITAL
        state.deaths.append({
            "life": state.current_life, "ended": today,
            "peak": state.lifetime_peak,
        })
        state.current_life += 1
        state.life_start_date = today
    state.history.append({
        **bet, "won": won,
        "settled_at": datetime.now(timezone.utc).isoformat(),
        "new_bankroll": new_bankroll,
    })
    state.balance = new_bankroll
    state.lifetime_peak = max(state.lifetime_peak, state.balance)
    return state


def settle_expired_bets(state: SportsBroState, now: Optional[datetime] = None) -> SportsBroState:
    """Auto-resolve any open bets whose end_date has passed.
    Sim mode: model_prob > market_prob → WIN; otherwise LOSS."""
    if not state.open_bets: return state
    now = now or datetime.now(timezone.utc)
    today_iso = now.date().isoformat()
    ts_iso = now.isoformat()
    remaining: List[Dict] = []
    settled_count = 0
    for bet in state.open_bets:
        end_str = bet.get("end_date") or bet.get("ends") or bet.get("end_time")
        if not end_str:
            remaining.append(bet); continue
        try:
            if isinstance(end_str, str):
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            else:
                end_dt = end_str
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
        except Exception:
            remaining.append(bet); continue
        if end_dt > now:
            remaining.append(bet); continue
        model_p = float(bet.get("model_prob") or 0.5)
        market_p = float(bet.get("market_prob") or bet.get("odds") or 0.5)
        stake = float(bet.get("stake") or STARTING_CAPITAL)
        won = model_p > market_p
        if won and market_p > 0:
            new_bankroll = stake * (1.0 / market_p)
            pnl = new_bankroll - stake
            state.balance = new_bankroll
        else:
            pnl = -stake
            state.balance = max(0.0, state.balance - stake)
        state.lifetime_peak = max(state.lifetime_peak, state.balance)
        state.history.append({
            "date": today_iso, "timestamp": ts_iso, "action": "CLOSE",
            "market": bet.get("label"), "sport": bet.get("sport"),
            "side": bet.get("side"), "won": won,
            "stake": round(stake, 4), "pnl": round(pnl, 4),
            "model_prob": model_p, "market_prob": market_p,
            "new_bankroll": round(state.balance, 4),
            "settled_at": ts_iso, "life": state.current_life,
        })
        settled_count += 1
        if state.balance < DEATH_THRESHOLD:
            state.deaths.append({
                "date": today_iso, "life": state.current_life,
                "final_balance": round(state.balance, 4),
                "peak_balance": round(state.lifetime_peak, 4),
                "epitaph": f"Sports Bro went bust on Life #{state.current_life}.",
            })
            state.balance = STARTING_CAPITAL
            state.current_life += 1
            state.life_start_date = today_iso
            state.lifetime_peak = STARTING_CAPITAL
            state.trades_today = 0
            state.history.append({
                "date": today_iso, "timestamp": ts_iso,
                "action": "REINCARNATION", "life": state.current_life,
            })
    state.open_bets = remaining
    if settled_count > 0:
        print(f"[sports_bro] settled {settled_count} expired bet(s); balance ${state.balance:.4f}")
    return state


def sports_bro_act(state: SportsBroState, markets: List[dict]) -> SportsBroState:
    today = datetime.now(timezone.utc).date().isoformat()
    ts = datetime.now(timezone.utc).isoformat()
    if state.last_action_date != today:
        state.trades_today = 0
        state.last_action_date = today
    if state.balance < DEATH_THRESHOLD and not state.open_bets:
        state.deaths.append({
            "date": today, "life": state.current_life,
            "final_balance": round(state.balance, 4),
            "peak_balance": round(state.lifetime_peak, 4),
            "epitaph": f"Sports Bro went bust on Life #{state.current_life}.",
        })
        state.balance = STARTING_CAPITAL
        state.current_life += 1
        state.life_start_date = today
        state.lifetime_peak = STARTING_CAPITAL
        state.trades_today = 0
        state.history.append({
            "date": today, "timestamp": ts,
            "action": "REINCARNATION", "life": state.current_life,
        })
    if state.trades_today >= MAX_TRADES_PER_DAY:
        state.history.append({
            "date": today, "timestamp": ts, "action": "HOLD",
            "reason": f"Daily trade cap ({MAX_TRADES_PER_DAY}) reached.",
            "balance": round(state.balance, 4),
        })
        return state
    if state.open_bets:
        state.history.append({
            "date": today, "timestamp": ts, "action": "HOLD",
            "reason": "Open bet still pending resolution.",
            "balance": round(state.balance, 4),
        })
        return state
    best = pick_best_bet(markets)
    if not best:
        state.history.append({
            "date": today, "timestamp": ts, "action": "NO_BET",
            "reason": "No eligible markets with positive edge found.",
            "balance": round(state.balance, 4),
        })
        return state
    bet = compose_bet(state, best)
    state.open_bets.append(bet)
    state.trades_today += 1
    state.history.append({
        "date": today, "timestamp": ts, "action": "BET",
        "market": bet.get("label"), "sport": bet.get("sport"),
        "side": bet.get("side"), "stake": round(state.balance, 4),
        "odds": bet.get("odds"), "ends": bet.get("ends"),
        "end_date": bet.get("end_date"),
        "model_prob": bet.get("model_prob"),
        "market_prob": bet.get("market_prob"),
        "life": state.current_life,
    })
    return state


class SportsBro(Agent):
    codename = "SPORTS_BRO"
    specialty = "Prediction Markets"
    temperament = ("Half-Kelly on the closest-resolving bet. Never sportsbooks. "
                   "Polymarket + Kalshi only. Lives for the 72-hour window.")
    inspiration = "The Avengers prop-bet guy"
    asset_classes = ("equity", "etf", "crypto")
    def applies_to(self, ctx: AssetContext) -> bool: return False
    def _judge(self, ctx: AssetContext) -> Verdict:
        return Verdict(agent=self.codename, ticker=ctx.ticker,
                       signal=Signal.ABSTAIN, conviction=0.0,
                       rationale="Sports Bro only bets on prediction markets, not financial assets.")
sports_bro = SportsBro()
