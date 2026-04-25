"""
silmaril.agents.jrr_token — JRR Token, the penny-token compounder.

Plays the lowest tier of the crypto market: tokens, not majors.
Splits his $1 budget 50/50:
  - $0.50 in the SUB tier  (under $100M market cap)  — high rug risk
  - $0.50 in the OVER tier ($100M – $1B market cap)  — established small caps

Each tier acts independently, with its own position and rotation logic.
12 trades / 24h cap across both tiers combined. Pump-and-dump windows
close fast; JRR rotates often.

Reincarnates at $0.05 like the other $1 compounders. The rug rate is
real: tokens vanish, projects abandon, JRR dies. He always comes back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .base import Agent, AssetContext, Signal, Verdict
from ..execution.detail import build_execution


# Tokens grouped by tier (market cap). In live mode this would come from
# CoinGecko's market-cap-ranked list; for demo purposes we hand-curate.
SUB_100M_TOKENS: Dict[str, str] = {
    "PEPE-USD":   "Pepe (memecoin)",
    "FLOKI-USD":  "Floki",
    "BONK-USD":   "Bonk",
    "WIF-USD":    "dogwifhat",
    "MOG-USD":    "Mog Coin",
    "TURBO-USD":  "Turbo",
    "BRETT-USD":  "Brett",
    "POPCAT-USD": "Popcat",
}

OVER_100M_TOKENS: Dict[str, str] = {
    "SHIB-USD":  "Shiba Inu",
    "PEPE-USD":  "Pepe",  # straddles tiers; placement varies by market cap
    "INJ-USD":   "Injective",
    "ARB-USD":   "Arbitrum",
    "OP-USD":    "Optimism",
    "STX-USD":   "Stacks",
    "RUNE-USD":  "THORChain",
    "FET-USD":   "Fetch.ai",
    "LDO-USD":   "Lido DAO",
    "GRT-USD":   "The Graph",
}

JRR_UNIVERSE = {**SUB_100M_TOKENS, **OVER_100M_TOKENS}

MAX_TRADES_PER_DAY = 12
DEATH_THRESHOLD = 0.05
TIER_BUDGET_PCT = 0.50  # 50/50 split


@dataclass
class TierState:
    """Per-tier state inside JRR Token."""
    name: str                            # 'SUB_100M' or 'OVER_100M'
    balance: float = 0.50                # half of $1.00
    current_position: Optional[Dict] = None
    history: List[Dict] = field(default_factory=list)


@dataclass
class JRRTokenState:
    """Persistent two-tier state for JRR Token."""
    sub_tier: TierState = field(default_factory=lambda: TierState(name="SUB_100M", balance=0.50))
    over_tier: TierState = field(default_factory=lambda: TierState(name="OVER_100M", balance=0.50))
    lifetime_peak: float = 1.00
    current_life: int = 1
    life_start_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat()
    )
    deaths: List[Dict] = field(default_factory=list)
    trades_today: int = 0
    last_action_date: str = ""

    @property
    def balance(self) -> float:
        """Total balance across both tiers."""
        return self.sub_tier.balance + self.over_tier.balance

    def to_dict(self) -> Dict:
        return {
            "codename": "JRR_TOKEN",
            "title": "The Two-Tier Token Trader",
            "balance": round(self.balance, 6),
            "tiers": {
                "sub_100m": {
                    "balance": round(self.sub_tier.balance, 6),
                    "current_position": self.sub_tier.current_position,
                    "recent_history": self.sub_tier.history[-15:],
                },
                "over_100m": {
                    "balance": round(self.over_tier.balance, 6),
                    "current_position": self.over_tier.current_position,
                    "recent_history": self.over_tier.history[-15:],
                },
            },
            "lifetime_peak": round(self.lifetime_peak, 6),
            "current_life": self.current_life,
            "life_start_date": self.life_start_date,
            "days_alive": self._days_alive(),
            "deaths": self.deaths,
            "trades_today": self.trades_today,
            "max_trades_per_day": MAX_TRADES_PER_DAY,
            "current_position": self._composite_position(),
            "history": self._merged_history(),
            "actions_this_life": len(self._merged_history()),
        }

    def _days_alive(self) -> int:
        try:
            start = datetime.fromisoformat(self.life_start_date).date()
            today = datetime.now(timezone.utc).date()
            return max(0, (today - start).days)
        except Exception:
            return 0

    def _composite_position(self) -> Optional[Dict]:
        """Returns the larger of the two tier positions, for headline display."""
        positions = []
        if self.sub_tier.current_position:
            positions.append((self.sub_tier.current_position, "SUB"))
        if self.over_tier.current_position:
            positions.append((self.over_tier.current_position, "OVER"))
        if not positions:
            return None
        # Return the more recent / larger
        return positions[0][0]

    def _merged_history(self) -> List[Dict]:
        """Sorted merge of both tiers' histories."""
        merged = []
        for h in self.sub_tier.history:
            merged.append({**h, "tier": "SUB_100M"})
        for h in self.over_tier.history:
            merged.append({**h, "tier": "OVER_100M"})
        merged.sort(key=lambda h: h.get("date", ""), reverse=True)
        return merged


class JRRToken(Agent):
    codename = "JRR_TOKEN"
    specialty = "Penny tokens — pump and dump"
    temperament = "Hyperactive, cynical, knows the rug is coming"
    inspiration = "The guy on Telegram who calls every coin '100x' until it isn't"
    asset_classes = ("crypto",)

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker in JRR_UNIVERSE

    def _judge(self, ctx: AssetContext) -> Verdict:
        if ctx.ticker not in JRR_UNIVERSE:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.ABSTAIN, conviction=0.0,
                rationale="JRR Token only trades the bottom of the barrel. This is too clean.",
            )

        chg = ctx.change_pct or 0.0
        sent = ctx.sentiment_score or 0.0
        is_sub = ctx.ticker in SUB_100M_TOKENS

        # Sub tier: pure momentum / pump detection
        if is_sub:
            if chg > 15:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.STRONG_BUY, conviction=0.9,
                    rationale=f"{ctx.ticker} pumping {chg:+.0f}%. JRR sends. Rug coming but we're early.",
                )
            if chg > 5:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.7,
                    rationale=f"{ctx.ticker} {chg:+.1f}%. JRR enters small. Tight stops.",
                )
            if chg < -25:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.HOLD, conviction=0.3,
                    rationale=f"{ctx.ticker} got rugged {chg:+.0f}%. JRR doesn't catch falling knives at this tier.",
                )
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.HOLD, conviction=0.4,
                rationale=f"{ctx.ticker} mid. JRR waits for a real pump.",
            )

        # Over tier: more measured, sentiment matters
        if chg > 8 and sent > 0.2:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.STRONG_BUY, conviction=0.8,
                rationale=f"{ctx.ticker} pumping {chg:+.1f}% with sentiment. JRR loads.",
            )
        if chg > 3:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.6,
                rationale=f"{ctx.ticker} {chg:+.1f}%. Decent setup, JRR opens a bag.",
            )
        if chg < -10 and sent < -0.2:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.5,
                rationale=f"{ctx.ticker} bleeding with negative sentiment. JRR exits.",
            )
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.HOLD, conviction=0.4,
            rationale=f"{ctx.ticker} consolidating. JRR waits.",
        )


jrr_token = JRRToken()


# ─────────────────────────────────────────────────────────────────
# Two-tier action logic
# ─────────────────────────────────────────────────────────────────

def jrr_token_act(
    state: JRRTokenState,
    ranked_candidates: List[Dict],
    prices: Dict[str, float],
) -> JRRTokenState:
    """
    JRR acts on both tiers independently. Each tier draws from its own
    50% budget. Combined trades/day cap is 12.
    """
    today = datetime.now(timezone.utc).date().isoformat()

    if state.last_action_date != today:
        state.trades_today = 0
        state.last_action_date = today

    # Death check (combined balance)
    if state.balance < DEATH_THRESHOLD:
        state.deaths.append({
            "date": today,
            "life": state.current_life,
            "final_balance": round(state.balance, 6),
            "peak_balance": round(state.lifetime_peak, 6),
            "epitaph": (f"JRR Token rugged on Life #{state.current_life}. "
                        f"Peaked at ${state.lifetime_peak:.4f}, busted at ${state.balance:.4f}. "
                        f"Tokens taketh away."),
        })
        # Reset both tiers to 50/50 of fresh $1
        state.sub_tier = TierState(name="SUB_100M", balance=0.50)
        state.over_tier = TierState(name="OVER_100M", balance=0.50)
        state.current_life += 1
        state.life_start_date = today
        state.lifetime_peak = 1.00
        state.trades_today = 0
        return state

    # Filter candidates by tier
    sub_picks = [c for c in ranked_candidates if c.get("ticker") in SUB_100M_TOKENS]
    over_picks = [c for c in ranked_candidates if c.get("ticker") in OVER_100M_TOKENS]

    # Act each tier independently if we have budget left for trades
    for tier, picks, tier_universe in [
        (state.sub_tier, sub_picks, SUB_100M_TOKENS),
        (state.over_tier, over_picks, OVER_100M_TOKENS),
    ]:
        if state.trades_today >= MAX_TRADES_PER_DAY:
            break
        _act_on_tier(state, tier, picks, prices, today, tier_universe)

    return state


def _act_on_tier(
    state: JRRTokenState,
    tier: TierState,
    picks: List[Dict],
    prices: Dict[str, float],
    today: str,
    tier_universe: Dict[str, str],
) -> None:
    """Run one tier's decision."""
    if not picks:
        tier.history.append({
            "date": today,
            "action": "HODL",
            "reason": f"No qualifying tokens in {tier.name} today.",
            "balance": round(tier.balance, 6),
        })
        return

    target = picks[0]
    target_ticker = target["ticker"]
    target_price = prices.get(target_ticker)
    if not target_price:
        return

    # If we already hold the same ticker, HODL
    if tier.current_position and tier.current_position["ticker"] == target_ticker:
        tier.history.append({
            "date": today,
            "action": "HODL",
            "ticker": target_ticker,
            "reason": f"Still JRR's top {tier.name} pick. HODL.",
            "balance": round(tier.balance, 6),
        })
        return

    # Sell existing position
    if tier.current_position:
        old = tier.current_position
        old_current = prices.get(old["ticker"], old["entry_price"])
        execution = build_execution(
            ticker=old["ticker"], asset_class="crypto", side="SELL",
            shares=old["shares"], price=old_current, available_before=0.0,
        )
        proceeds = execution["net_proceeds"] or (old["shares"] * old_current)
        pnl_pct = ((old_current / old["entry_price"]) - 1) * 100 if old["entry_price"] else 0.0
        tier.history.append({
            "date": today,
            "action": "SELL",
            "ticker": old["ticker"],
            "shares": old["shares"],
            "price": old_current,
            "proceeds": round(proceeds, 6),
            "pnl_pct": round(pnl_pct, 2),
            "execution": execution,
        })
        tier.balance = round(proceeds, 6)
        state.lifetime_peak = max(state.lifetime_peak, state.balance)
        state.trades_today += 1

    # Buy the new target
    available = tier.balance
    shares = available / target_price
    for _ in range(3):
        test_exec = build_execution(
            ticker=target_ticker, asset_class="crypto", side="BUY",
            shares=shares, price=target_price, available_before=available,
        )
        over_amt = (test_exec["net_cost"] or 0) - available
        if over_amt <= 0.00001:
            break
        shares -= (over_amt / target_price) * 1.01
    execution = build_execution(
        ticker=target_ticker, asset_class="crypto", side="BUY",
        shares=shares, price=target_price, available_before=available,
    )
    tier.current_position = {
        "ticker": target_ticker,
        "name": tier_universe.get(target_ticker, target_ticker),
        "shares": round(shares, 8),
        "entry_price": round(target_price, 6),
        "entry_date": today,
        "thesis": (f"JRR {tier.name} bag — momentum / sentiment edge. "
                   f"Stops are tight, exit fast."),
        "execution": execution,
    }
    tier.history.append({
        "date": today,
        "action": "BUY",
        "ticker": target_ticker,
        "shares": round(shares, 8),
        "entry_price": round(target_price, 6),
        "allocated": round(available, 6),
        "execution": execution,
    })
    state.trades_today += 1
