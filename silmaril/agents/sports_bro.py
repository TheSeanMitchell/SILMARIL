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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional


# Per-sport prior win-rate for Sports Bro's edge (rough; updates Bayesian)
SPORT_PRIORS = {
    "nba": 0.54, "nfl": 0.53, "mlb": 0.52, "nhl": 0.52,
    "epl": 0.52, "champions_league": 0.52,
    "tennis": 0.55, "mma": 0.51, "golf": 0.50,
    "default": 0.50,
}

CLOSEST_HOURS = 72      # primary window
FALLBACK_HOURS = 168    # 7 days


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
        # Implied probability from price (assume decimal odds or % market)
        price = m.get("price") or m.get("yes_price") or m.get("odds")
        if not price:
            continue
        try:
            price = float(price)
        except Exception:
            continue
        # Treat price as probability if 0<p<1, else convert from decimal odds
        if 0 < price < 1:
            implied_p = price
        elif price > 1:
            implied_p = 1.0 / price
        else:
            continue
        # Edge: prior - implied
        edge = prior - implied_p
        if edge <= 0:
            continue
        h = _hours_until(m, now) or 999
        # Score: edge × recency-bonus (closer is better)
        recency_bonus = 1.0 + max(0, (CLOSEST_HOURS - h) / CLOSEST_HOURS)
        scored.append((m, edge * recency_bonus, h))

    if not scored:
        return None
    # Take top-3 by score, then pick the closest among them
    scored.sort(key=lambda r: -r[1])
    top3 = scored[:3]
    top3.sort(key=lambda r: r[2])
    return top3[0][0]


def compose_bet(state: dict, market: dict) -> dict:
    """Stake the entire current bankroll on this single bet."""
    bankroll = float(state.get("bankroll", 1.0))
    return {
        "market_id": market.get("id") or market.get("market_id"),
        "sport": market.get("sport"),
        "label": market.get("label") or market.get("title"),
        "side": market.get("recommended_side") or "YES",
        "stake": bankroll,
        "odds": market.get("price") or market.get("odds"),
        "ends": market.get("end_date") or market.get("end_time"),
        "placed_at": datetime.now(timezone.utc).isoformat(),
    }


def load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {"bankroll": 1.0, "history": [], "active_bet": None, "lifetime_resets": 0}
    try:
        return json.loads(state_path.read_text())
    except Exception:
        return {"bankroll": 1.0, "history": [], "active_bet": None, "lifetime_resets": 0}


def save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, default=str))


def settle_active_bet(state: dict, won: bool, payout_multiplier: float = 2.0) -> dict:
    """Resolve the active bet. If won, multiply by payout. If lost, reset to $1."""
    bet = state.get("active_bet")
    if not bet:
        return state
    if won:
        new_bankroll = float(bet.get("stake", 1.0)) * payout_multiplier
    else:
        new_bankroll = 1.0
        state["lifetime_resets"] = state.get("lifetime_resets", 0) + 1
    state.setdefault("history", []).append({
        **bet,
        "won": won,
        "settled_at": datetime.now(timezone.utc).isoformat(),
        "new_bankroll": new_bankroll,
    })
    state["bankroll"] = new_bankroll
    state["active_bet"] = None
    return state
