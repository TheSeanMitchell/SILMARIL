"""silmaril.agents.sports_bro — Prediction-markets compounder. v2 with settle_expired_bets."""
from __future__ import annotations
import json
import random
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
DEATH_THRESHOLD = 500.00     # $10K migration: death threshold scaled 50× too
MAX_TRADES_PER_DAY = 8
STARTING_CAPITAL = 10_000.00 # $10K migration: was 10.00; reincarnation now reseeds at $10K

# ── ALPHA 7.0 STAKING DISCIPLINE ──────────────────────────────────
# Prior behaviour staked the ENTIRE bankroll on every market and settled
# deterministically (model_prob > market_prob ⇒ guaranteed win paying
# 1/market_prob). That compounded a $10K seed into tens of billions of
# fantasy dollars (≈ +382,000,000%), which destroyed the leaderboard and
# the compounder-matchup chart. SPORTS_BRO is a *simulated* agent and is
# fully separate from the real Alpaca paper accounts (LEGACY/H3/H5).
#
# Fix:
#   • Fractional (half) Kelly sizing, hard-capped at MAX_STAKE_FRACTION of
#     bankroll per bet — a single bet can no longer bankrupt or moonshot it.
#   • Outcomes are now drawn randomly against a bounded "true" probability
#     that is mostly the market's implied probability (markets are roughly
#     efficient) with a small skill tilt toward the model. No guaranteed wins.
KELLY_FRACTION = 0.5          # half-Kelly
MAX_STAKE_FRACTION = 0.10     # never risk more than 10% of bankroll on one bet
MIN_STAKE = 1.0               # don't place sub-$1 bets
# 0.0 = market-efficient outcomes (zero expected drift): the bankroll random-
# walks and can bust → reincarnate, but never systematically balloons. Raise
# slightly (e.g. 0.05) only if you want to model a genuine edge for the agent.
SKILL_WEIGHT = 0.0


def _implied_prob(odds) -> Optional[float]:
    """Normalise a price/odds value to an implied probability in (0, 1)."""
    try:
        p = float(odds)
    except (TypeError, ValueError):
        return None
    if 0 < p < 1:
        return p
    if p > 1:                 # decimal odds → implied probability
        return 1.0 / p
    return None


def _kelly_stake(balance: float, model_p: Optional[float], market_p: Optional[float]) -> float:
    """Half-Kelly stake for a binary YES bought at price ``market_p``, capped.

    Kelly fraction f* = (p*(b+1) - 1) / b, with net odds b = 1/market_p - 1
    and p = model's probability of YES. Returns a dollar amount; 0.0 when
    there is no positive-edge stake.
    """
    if balance <= 0:
        return 0.0
    mp = _implied_prob(market_p)
    if mp is None or not (0 < mp < 1):
        return 0.0
    b = (1.0 / mp) - 1.0
    if b <= 0:
        return 0.0
    p = model_p if (model_p is not None and 0 < model_p < 1) else mp
    f_star = (p * (b + 1.0) - 1.0) / b
    f = max(0.0, f_star) * KELLY_FRACTION
    f = min(f, MAX_STAKE_FRACTION)
    return round(balance * f, 4)


def _resolve_outcome(model_p: float, market_p: float) -> bool:
    """Randomly resolve a YES bet. True probability is mostly the market's
    implied probability with a small tilt toward the model, bounded to
    [0.02, 0.98] so nothing is ever a sure thing."""
    true_p = (1.0 - SKILL_WEIGHT) * market_p + SKILL_WEIGHT * model_p
    true_p = max(0.02, min(0.98, true_p))
    return random.random() < true_p


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
    sport = (market.get("sport") or "default").lower()
    market_prob = (market.get("market_prob") or market.get("price")
                   or market.get("yes_price") or market.get("odds"))
    model_prob = market.get("model_prob")
    if model_prob is None:
        model_prob = SPORT_PRIORS.get(sport, SPORT_PRIORS["default"])
    # Half-Kelly, hard-capped — NEVER the whole bankroll (Alpha 7.0).
    stake = _kelly_stake(state.balance, model_prob, market_prob)
    if stake < MIN_STAKE:
        # Positive edge but a tiny Kelly stake; place a token bet (still far
        # under the bankroll) so the agent stays active without risking ruin.
        stake = min(MIN_STAKE, round(state.balance * MAX_STAKE_FRACTION, 4))
    return {
        "market_id": market.get("id") or market.get("market_id"),
        "sport": market.get("sport"),
        "label": market.get("label") or market.get("title") or market.get("market"),
        "side": market.get("recommended_side") or "YES",
        "stake": round(stake, 4),
        "odds": market.get("price") or market.get("odds"),
        "model_prob": model_prob,
        "market_prob": market_prob,
        "ends": market.get("end_date") or market.get("end_time"),
        "end_date": market.get("end_date") or market.get("end_time"),
        "placed_at": datetime.now(timezone.utc).isoformat(),
    }


def settle_active_bet(state: SportsBroState, won: bool, payout_multiplier: float = 2.0) -> SportsBroState:
    if not state.open_bets: return state
    bet = state.open_bets.pop(0)
    today = datetime.now(timezone.utc).date().isoformat()
    # ALPHA 7.0: only the stake is at risk (was: doubled / reset the whole
    # bankroll). This path is currently unused — settle_expired_bets is the
    # live settlement — but it is kept correct so it can't reintroduce the
    # fantasy-compounding bug if wired up later.
    stake = float(bet.get("stake") or 0.0)
    stake = min(stake, max(0.0, state.balance))
    if won:
        pnl = stake * (payout_multiplier - 1.0)
        state.balance = max(0.0, state.balance + pnl)
    else:
        pnl = -stake
        state.balance = max(0.0, state.balance + pnl)
        if state.balance < DEATH_THRESHOLD:
            state.deaths.append({
                "life": state.current_life, "ended": today,
                "peak": state.lifetime_peak,
            })
            state.current_life += 1
            state.life_start_date = today
            state.balance = STARTING_CAPITAL
            state.lifetime_peak = STARTING_CAPITAL
    state.history.append({
        **bet, "won": won,
        "settled_at": datetime.now(timezone.utc).isoformat(),
        "pnl": round(pnl, 4),
        "new_bankroll": round(state.balance, 4),
    })
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
        market_p = _implied_prob(bet.get("market_prob") or bet.get("odds")) or 0.5
        stake = float(bet.get("stake") or 0.0)
        stake = min(stake, max(0.0, state.balance))   # can't risk more than we hold
        won = _resolve_outcome(model_p, market_p)
        if won and market_p > 0:
            payout = stake * (1.0 / market_p)          # YES bought at market_p
            pnl = payout - stake
        else:
            pnl = -stake
        # Only the stake is at risk — the rest of the bankroll is untouched.
        state.balance = max(0.0, state.balance + pnl)
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
        "side": bet.get("side"), "stake": bet.get("stake"),
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
