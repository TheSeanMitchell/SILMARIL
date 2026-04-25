"""
silmaril.agents.cryptobro — CryptoBro, the multi-trade crypto compounder.

CryptoBro is the third $1 compounder in the SILMARIL trinity, alongside
SCROOGE and MIDAS. Where they each take exactly one position per day,
CryptoBro has multi-trade-per-day permission — up to 5 transactions per
cycle. He plays vibes, momentum, and the dip. He talks in third person,
uses HODL/ser/wagmi/diamond hands language, and trades only crypto.

Universe: BTC, ETH, SOL, AVAX, DOGE, LINK, MATIC, ADA, XRP, DOT, ATOM.
Fees: Coinbase 40 bps taker + spread cost. No SEC/FINRA on crypto.
Reincarnation: at $0.05, like the others.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .base import Agent, AssetContext, Signal, Verdict
from ..execution.detail import build_execution


# ─────────────────────────────────────────────────────────────────
# CryptoBro's universe — only liquid crypto, no tokens-of-tokens
# ─────────────────────────────────────────────────────────────────

CRYPTOBRO_UNIVERSE: Dict[str, str] = {
    "BTC-USD":   "Bitcoin",
    "ETH-USD":   "Ethereum",
    "SOL-USD":   "Solana",
    "AVAX-USD":  "Avalanche",
    "DOGE-USD":  "Dogecoin",
    "LINK-USD":  "Chainlink",
    "MATIC-USD": "Polygon",
    "ADA-USD":   "Cardano",
    "XRP-USD":   "XRP",
    "DOT-USD":   "Polkadot",
    "ATOM-USD":  "Cosmos",
}

# Max trades per cycle. CryptoBro can rotate up to this many times in
# a single run if his vibe-meter says different things on different coins.
MAX_TRADES_PER_DAY = 5

DEATH_THRESHOLD = 0.05  # below 5 cents → reincarnation


# ─────────────────────────────────────────────────────────────────
# State — what persists across runs
# ─────────────────────────────────────────────────────────────────

@dataclass
class CryptoBroState:
    """Persistent state for CryptoBro across runs."""
    balance: float = 1.00
    current_position: Optional[Dict] = None
    lifetime_peak: float = 1.00
    current_life: int = 1
    life_start_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat()
    )
    history: List[Dict] = field(default_factory=list)
    deaths: List[Dict] = field(default_factory=list)
    trades_today: int = 0
    last_action_date: str = ""

    def to_dict(self) -> Dict:
        return {
            "codename": "CRYPTOBRO",
            "title": "The Degenerate Optimist",
            "balance": round(self.balance, 6),
            "current_position": self.current_position,
            "lifetime_peak": round(self.lifetime_peak, 6),
            "current_life": self.current_life,
            "life_start_date": self.life_start_date,
            "days_alive": self._days_alive(),
            "actions_this_life": len(self.history),
            "history": self.history,
            "deaths": self.deaths,
            "trades_today": self.trades_today,
            "max_trades_per_day": MAX_TRADES_PER_DAY,
        }

    def _days_alive(self) -> int:
        try:
            start = datetime.fromisoformat(self.life_start_date).date()
            today = datetime.now(timezone.utc).date()
            return max(0, (today - start).days)
        except Exception:
            return 0


# ─────────────────────────────────────────────────────────────────
# The agent (votes on crypto only, used in the main debate too)
# ─────────────────────────────────────────────────────────────────

class CryptoBro(Agent):
    """CryptoBro as a voting agent in the main debate."""

    codename = "CRYPTOBRO"
    specialty = "Crypto momentum & vibes"
    temperament = "Hyperactive, opportunistic, third-person"
    inspiration = "Every guy at the bar in 2021"
    asset_classes = ("crypto",)

    def _judge(self, ctx: AssetContext) -> Verdict:
        if ctx.ticker not in CRYPTOBRO_UNIVERSE:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.ABSTAIN, conviction=0.0,
                rationale="CryptoBro doesn't touch tradfi, ser.",
            )

        chg = ctx.change_pct or 0.0
        sent = ctx.sentiment_score or 0.0

        if chg > 4 and sent > 0.2:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.STRONG_BUY, conviction=0.85,
                rationale=f"CryptoBro is sending it. {ctx.ticker} ripping {chg:+.1f}% with bullish vibes — wagmi 🚀",
            )
        if chg > 1.5:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.65,
                rationale=f"CryptoBro likes the green candle on {ctx.ticker}. Diamond hands engaged.",
            )
        if chg < -5 and sent < -0.2:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.7,
                rationale=f"CryptoBro is buying the dip on {ctx.ticker}. He believes in the tech, ser.",
            )
        if -1.5 < chg < 1.5:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.HOLD, conviction=0.4,
                rationale=f"CryptoBro is HODLing. {ctx.ticker} is consolidating — patience.",
            )
        if chg < -2:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.HOLD, conviction=0.5,
                rationale=f"CryptoBro is not selling at a loss. {ctx.ticker} will recover. Diamond hands.",
            )
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.HOLD, conviction=0.35,
            rationale=f"CryptoBro is watching {ctx.ticker}. The chart is mid right now.",
        )


cryptobro = CryptoBro()


# ─────────────────────────────────────────────────────────────────
# Trading logic (multi-trade per day)
# ─────────────────────────────────────────────────────────────────

def cryptobro_act(
    state: CryptoBroState,
    ranked_candidates: List[Dict],
    prices: Dict[str, float],
) -> CryptoBroState:
    """
    CryptoBro acts. Unlike SCROOGE and MIDAS who do one trade per day,
    CryptoBro can rotate up to MAX_TRADES_PER_DAY times if conditions
    keep shifting. Each rotation is its own SELL → BUY pair with full
    fee accounting.

    ranked_candidates: list of dicts sorted by consensus_score desc,
        each with {ticker, consensus, signal, ...}. Filtered to crypto.
    """
    today = datetime.now(timezone.utc).date().isoformat()

    # Reset daily trade counter on new day
    if state.last_action_date != today:
        state.trades_today = 0
        state.last_action_date = today

    # ── Death check ─────────────────────────────────────────────
    if state.balance < DEATH_THRESHOLD:
        state.deaths.append({
            "date": today,
            "life": state.current_life,
            "final_balance": round(state.balance, 6),
            "peak_balance": round(state.lifetime_peak, 6),
            "epitaph": (
                f"CryptoBro got rugged on Life #{state.current_life}. "
                f"Peaked at ${state.lifetime_peak:.4f}, busted at ${state.balance:.4f}. "
                f"He'll be back, ser. He always comes back."
            ),
        })
        state.balance = 1.00
        state.current_position = None
        state.current_life += 1
        state.life_start_date = today
        state.lifetime_peak = 1.00
        state.history.append({
            "date": today,
            "action": "REINCARNATION",
            "life": state.current_life,
            "note": "CryptoBro respawns. Diamond hands forever.",
        })
        state.trades_today = 0

    # Filter to crypto-only candidates ranked by consensus
    crypto_picks = [
        c for c in ranked_candidates
        if c.get("ticker", "") in CRYPTOBRO_UNIVERSE
    ]

    if not crypto_picks:
        # No crypto signals today — HODL whatever we have, log the day
        state.history.append({
            "date": today,
            "action": "HODL",
            "reason": "CryptoBro sees no setups in the crypto market today. He waits.",
            "balance": round(state.balance, 6),
            "trades_today": state.trades_today,
        })
        return state

    # ── Decision: should CryptoBro rotate? ──────────────────────
    # If holding nothing, BUY the top-ranked crypto signal.
    # If already holding, only rotate if the top signal is meaningfully
    # better than what we have AND we haven't burned our daily trades.
    target = crypto_picks[0]
    target_ticker = target["ticker"]
    target_price = prices.get(target_ticker)

    if target_price is None:
        return state

    # Sell-side: do we already hold something?
    held_ticker = state.current_position["ticker"] if state.current_position else None

    # If holding the same coin: HODL
    if held_ticker == target_ticker:
        state.history.append({
            "date": today,
            "action": "HODL",
            "ticker": held_ticker,
            "reason": f"CryptoBro is HODLing {held_ticker}. Still his top conviction. Diamond hands.",
            "balance": round(state.balance, 6),
            "trades_today": state.trades_today,
        })
        return state

    # If we've already burned the daily budget: HODL
    if state.trades_today >= MAX_TRADES_PER_DAY:
        state.history.append({
            "date": today,
            "action": "HODL",
            "ticker": held_ticker or "—",
            "reason": (
                f"CryptoBro has used all {MAX_TRADES_PER_DAY} trades today. "
                f"Even degens need rest, ser."
            ),
            "balance": round(state.balance, 6),
            "trades_today": state.trades_today,
        })
        return state

    # ── SELL the current position if any ────────────────────────
    if state.current_position:
        old = state.current_position
        old_ticker = old["ticker"]
        old_shares = old["shares"]
        old_entry = old["entry_price"]
        old_current = prices.get(old_ticker, old_entry)

        execution = build_execution(
            ticker=old_ticker, asset_class="crypto", side="SELL",
            shares=old_shares, price=old_current, available_before=0.0,
        )
        proceeds = execution["net_proceeds"] or (old_shares * old_current)
        pnl_pct = ((old_current / old_entry) - 1) * 100 if old_entry else 0.0

        state.history.append({
            "date": today,
            "action": "SELL",
            "ticker": old_ticker,
            "shares": round(old_shares, 8),
            "exit_price": round(old_current, 4),
            "entry_price": round(old_entry, 4),
            "proceeds": round(proceeds, 6),
            "pnl_pct": round(pnl_pct, 2),
            "balance_after": round(proceeds, 6),
            "life": state.current_life,
            "execution": execution,
            "narrative": _sell_narrative(old_ticker, pnl_pct),
        })
        state.balance = round(proceeds, 6)
        state.lifetime_peak = max(state.lifetime_peak, state.balance)

    # ── BUY the new target ──────────────────────────────────────
    available = state.balance
    shares = available / target_price
    for _ in range(3):
        test_exec = build_execution(
            ticker=target_ticker, asset_class="crypto", side="BUY",
            shares=shares, price=target_price, available_before=available,
        )
        over = (test_exec["net_cost"] or 0) - available
        if over <= 0.00001:
            break
        shares -= (over / target_price) * 1.01

    execution = build_execution(
        ticker=target_ticker, asset_class="crypto", side="BUY",
        shares=shares, price=target_price, available_before=available,
    )
    state.current_position = {
        "ticker": target_ticker,
        "name": CRYPTOBRO_UNIVERSE.get(target_ticker, target_ticker),
        "shares": round(shares, 8),
        "entry_price": round(target_price, 4),
        "entry_date": today,
        "thesis": (
            f"CryptoBro is sending it on {target_ticker}. "
            f"Consensus {target['consensus']['signal']}. Wagmi 🚀"
        ),
        "execution": execution,
    }
    state.history.append({
        "date": today,
        "action": "BUY",
        "ticker": target_ticker,
        "shares": round(shares, 8),
        "entry_price": round(target_price, 4),
        "allocated": round(available, 6),
        "life": state.current_life,
        "execution": execution,
        "narrative": _buy_narrative(target_ticker, target['consensus']['signal']),
    })
    state.trades_today += 1
    return state


# ─────────────────────────────────────────────────────────────────
# Bro-voice narrative generators
# ─────────────────────────────────────────────────────────────────

def _buy_narrative(ticker: str, signal: str) -> str:
    """CryptoBro's bro-talk for a BUY."""
    coin = ticker.replace("-USD", "")
    if signal == "STRONG_BUY":
        return f"CryptoBro is going all-in on {coin}. This is THE pick. Wagmi, ser."
    if signal == "BUY":
        return f"CryptoBro is loading the bag on {coin}. The chart is sending."
    return f"CryptoBro is buying {coin}. Diamond hands activated."


def _sell_narrative(ticker: str, pnl_pct: float) -> str:
    """CryptoBro's bro-talk for a SELL."""
    coin = ticker.replace("-USD", "")
    if pnl_pct > 5:
        return f"CryptoBro took profits on {coin} ({pnl_pct:+.1f}%). Number go up. Few understand."
    if pnl_pct > 0:
        return f"CryptoBro is stacking sats. Closed {coin} for {pnl_pct:+.1f}%. Slow and steady, ser."
    if pnl_pct > -5:
        return f"CryptoBro is rotating out of {coin} ({pnl_pct:+.1f}%). It's not a loss, it's tuition."
    return (
        f"CryptoBro got chopped on {coin} ({pnl_pct:+.1f}%). "
        f"He's not crying, you're crying. Onward."
    )
