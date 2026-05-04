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
DEATH_THRESHOLD = 0.50
TIER_BUDGET_PCT = 0.50  # 50/50 split


@dataclass
class TierState:
    """Per-tier state inside JRR Token."""
    name: str                            # 'SUB_100M' or 'OVER_100M'
    balance: float = 5.00                # half of $1.00
    current_position: Optional[Dict] = None
    history: List[Dict] = field(default_factory=list)


@dataclass
class JRRTokenState:
    """Persistent two-tier state for JRR Token."""
    sub_tier: TierState = field(default_factory=lambda: TierState(name="SUB_100M", balance=5.00))
    over_tier: TierState = field(default_factory=lambda: TierState(name="OVER_100M", balance=5.00))
    lifetime_peak: float = 10.00
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
        # BUG 3: sort by timestamp when available, fall back to date
        merged.sort(key=lambda h: h.get("timestamp") or h.get("date", ""), reverse=False)
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
        state.sub_tier = TierState(name="SUB_100M", balance=5.00)
        state.over_tier = TierState(name="OVER_100M", balance=5.00)
        state.current_life += 1
        state.life_start_date = today
        state.lifetime_peak = 10.00
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
    # BUG 3 FIX: add timestamp to every history.append so the UI renders
    # correct times instead of defaulting to midnight (17:00 Las Vegas time)
    ts = datetime.now(timezone.utc).isoformat()

    if not picks:
        tier.history.append({
            "date": today,
            "timestamp": ts,
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
            "timestamp": ts,
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
            "timestamp": ts,
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
        "timestamp": ts,
        "action": "BUY",
        "ticker": target_ticker,
        "shares": round(shares, 8),
        "entry_price": round(target_price, 6),
        "allocated": round(available, 6),
        "execution": execution,
    })
    state.trades_today += 1



================================================
FILE: silmaril/agents/kestrel.py
================================================
"""
silmaril.agents.kestrel — The Patient Hunter.

KESTREL waits for coiled Bollinger bands (low volatility compression)
paired with directional confirmation, then takes high-reward/risk
entries with very tight stops. Most days it ABSTAINs. The setups it
finds are rare but unusually clean.

Decision logic:
  - Requires BB width < 6% (coiled)
  - Requires price touching upper band with trend up → BUY
  - Requires price touching lower band with trend down → SELL
  - Uses 1 ATR stops (tight) for outsized R:R.
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Kestrel(Agent):
    codename = "KESTREL"
    specialty = "Precision Entry"
    temperament = "Hunts patiently. Most days, no shot. When the shot comes, perfect."
    inspiration = "Hawkeye — precision, not volume"
    asset_classes = ("equity", "etf")

    BB_COILED = 0.06             # width as fraction of mid band
    UPPER_BAND_MULT = 1.8        # stdev multiple for trigger

    def _judge(self, ctx: AssetContext) -> Verdict:
        if not ctx.price or not ctx.bb_width or not ctx.sma_20 or not ctx.atr_14:
            return self._abstain(ctx, "awaiting a clean setup")

        if ctx.bb_width > self.BB_COILED:
            return self._abstain(ctx, f"bands not coiled (width {ctx.bb_width:.3f})")

        # Need trend direction to pick side
        trend_up = ctx.sma_50 and ctx.sma_20 > ctx.sma_50

        # Simple proxy for band-edge: price vs sma_20 scaled by atr
        dist_from_mid = ctx.price - ctx.sma_20
        atr_dist = dist_from_mid / ctx.atr_14 if ctx.atr_14 else 0

        # Long setup: coiled + trend up + price at/above upper
        if trend_up and atr_dist > 1.0:
            conv = 0.72
            entry = ctx.price
            stop = ctx.price - 1.0 * ctx.atr_14
            target = ctx.price + 3.0 * ctx.atr_14  # 3:1 R:R on tight stop
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=conv,
                rationale=(
                    f"Coiled bands (width {ctx.bb_width:.3f}) + trend up + "
                    f"price {atr_dist:.1f} ATR above mid — precision long."
                ),
                factors={"bb_width": round(ctx.bb_width, 4), "atr_distance": round(atr_dist, 2)},
                suggested_entry=round(entry, 2),
                suggested_stop=round(stop, 2),
                suggested_target=round(target, 2),
                invalidation=f"Close below ${stop:.2f} (1 ATR stop) — setup failed cleanly.",
            )

        # Short setup: coiled + trend down + price at/below lower
        if ctx.sma_50 and ctx.sma_20 < ctx.sma_50 and atr_dist < -1.0:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.65,
                rationale=(
                    f"Coiled bands + trend down + price {abs(atr_dist):.1f} ATR below mid — "
                    f"precision short setup."
                ),
                factors={"bb_width": round(ctx.bb_width, 4)},
            )

        return self._abstain(ctx, "coiled but no directional trigger")

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


kestrel = Kestrel()



================================================
FILE: silmaril/agents/kestrel_plus.py
================================================
"""
silmaril.agents.kestrel_plus — The Hurst-Aware Mean Reverter.

The original KESTREL fades RSI extremes. KESTREL_PLUS first measures
whether the underlying time-series is actually mean-reverting before
fading anything. If Hurst exponent < 0.45 → true mean reverter, fade
extremes. If Hurst > 0.55 → trender, stay silent. Between → no signal.

This fixes the trap of fading a strong trend just because RSI > 70.

Computes Hurst via Rescaled Range (R/S) analysis on log returns.
"""
from __future__ import annotations

import math
from typing import List, Optional

from .base import Agent, AssetContext, Signal, Verdict


def _hurst_rs(series: List[float]) -> Optional[float]:
    """Rescaled-range Hurst estimator. Returns None if insufficient data."""
    if not series or len(series) < 64:
        return None

    # Log returns
    rets: List[float] = []
    for i in range(1, len(series)):
        a, b = series[i-1], series[i]
        if a is None or b is None or a <= 0 or b <= 0:
            return None
        rets.append(math.log(b / a))
    if len(rets) < 32:
        return None

    # Geometric chunk sizes from 8 to len/2
    max_chunk = len(rets) // 2
    chunks = []
    s = 8
    while s <= max_chunk:
        chunks.append(s)
        s = int(s * 1.6)
    chunks = sorted(set(chunks))
    if len(chunks) < 3:
        return None

    log_n: List[float] = []
    log_rs: List[float] = []
    for size in chunks:
        groups = len(rets) // size
        if groups == 0:
            continue
        rs_vals = []
        for g in range(groups):
            seg = rets[g*size:(g+1)*size]
            mean = sum(seg) / size
            cum = 0.0
            cum_seq: List[float] = []
            for r in seg:
                cum += r - mean
                cum_seq.append(cum)
            R = max(cum_seq) - min(cum_seq)
            var = sum((r - mean)**2 for r in seg) / size
            S = math.sqrt(var)
            if S > 0:
                rs_vals.append(R / S)
        if rs_vals:
            log_n.append(math.log(size))
            log_rs.append(math.log(sum(rs_vals) / len(rs_vals)))

    if len(log_n) < 3:
        return None

    # OLS slope = Hurst
    nx = len(log_n)
    mx = sum(log_n) / nx
    my = sum(log_rs) / nx
    num = sum((log_n[i] - mx) * (log_rs[i] - my) for i in range(nx))
    den = sum((log_n[i] - mx)**2 for i in range(nx))
    if den == 0:
        return None
    return num / den


class KestrelPlus(Agent):
    codename = "KESTREL+"
    specialty = "Hurst-Aware Mean Reversion"
    temperament = (
        "Smarter than the original KESTREL. Measures whether a series "
        "is actually mean-reverting before fading anything. Stays silent "
        "on trenders. Fades extremes only when the math says fade."
    )
    inspiration = "Kestrel — the falcon that hovers, then dives only on confirmed prey"
    asset_classes = ("equity", "etf", "crypto")

    HURST_REVERTER = 0.45
    HURST_TRENDER = 0.55

    def _judge(self, ctx: AssetContext) -> Verdict:
        ph = ctx.price_history or []
        rsi = ctx.rsi_14

        if len(ph) < 64 or rsi is None:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.HOLD,
                conviction=0.0,
                rationale="insufficient history for Hurst analysis",
            )

        H = _hurst_rs(ph)
        if H is None:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.HOLD,
                conviction=0.0,
                rationale="Hurst undefined",
            )

        factors = {"hurst": round(H, 3), "rsi": round(rsi, 1)}

        # Trender — stay silent
        if H >= self.HURST_TRENDER:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale=f"H={H:.2f} → trender, mean-reversion N/A",
                factors=factors,
            )

        # Ambiguous middle — no edge
        if H >= self.HURST_REVERTER:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.HOLD,
                conviction=0.0,
                rationale=f"H={H:.2f} → no clear regime",
                factors=factors,
            )

        # True mean reverter — fade RSI extremes
        if rsi >= 75:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.SELL,
                conviction=min(0.80, 0.45 + (rsi - 75) * 0.02),
                rationale=f"H={H:.2f} reverter, RSI {rsi:.0f} overbought",
                factors=factors,
            )
        if rsi <= 25:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.BUY,
                conviction=min(0.80, 0.45 + (25 - rsi) * 0.02),
                rationale=f"H={H:.2f} reverter, RSI {rsi:.0f} oversold",
                factors=factors,
            )

        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=Signal.HOLD,
            conviction=0.0,
            rationale=f"H={H:.2f} reverter, RSI {rsi:.0f} not extreme",
            factors=factors,
        )


kestrel_plus = KestrelPlus()



================================================
FILE: silmaril/agents/magus.py
================================================
"""
silmaril.agents.magus — The Time Reader.

MAGUS plays seasonal patterns: turn-of-month effects, Santa rally,
sell-in-May, day-of-week biases. These effects are small but
statistically persistent, especially on index-level assets.

Doctor Strange's archetype: reading patterns across time.

Decision logic:
  - Late December on indices → seasonal bullish bias
  - Early-to-mid May on indices → seasonal bearish bias
  - Last trading day of month → bullish bias (turn-of-month effect)
  - Friday in uptrending market → mild bullish bias
  - Abstains when no calendar edge is active
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .base import Agent, AssetContext, Signal, Verdict


INDEX_TICKERS = {"SPY", "QQQ", "DIA", "IWM", "VTI"}


class Magus(Agent):
    codename = "MAGUS"
    specialty = "Seasonality & Time"
    temperament = "Reads patterns across time. History rhymes more than it repeats, but it rhymes."
    inspiration = "Doctor Strange — the reader of timelines"
    asset_classes = ("etf",)

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker.upper() in INDEX_TICKERS

    def _judge(self, ctx: AssetContext) -> Verdict:
        now = datetime.now(timezone.utc)
        month, day, weekday = now.month, now.day, now.weekday()

        signals = []

        # Santa rally window (Dec 20 – Jan 2)
        if (month == 12 and day >= 20) or (month == 1 and day <= 2):
            signals.append(("santa_rally", Signal.BUY, 0.5, "Santa Rally window — late-Dec/early-Jan bullish bias."))

        # Sell-in-May (May 5–31)
        if month == 5 and 5 <= day <= 31:
            signals.append(("sell_in_may", Signal.SELL, 0.45, "Sell-in-May seasonal window — reducing exposure."))

        # Turn-of-month (last 3 days of month + first 2)
        if day >= 28 or day <= 2:
            signals.append(("turn_of_month", Signal.BUY, 0.4, "Turn-of-month effect — modest bullish bias."))

        # Friday in clear uptrend
        if weekday == 4 and ctx.sma_20 and ctx.price and ctx.price > ctx.sma_20:
            signals.append(("friday_drift", Signal.BUY, 0.4, "Friday in uptrend — weekend effect."))

        if not signals:
            return self._abstain(ctx, f"no active seasonal pattern for {ctx.ticker}")

        # Pick the highest-conviction of the active signals
        _, sig, conv, reason = max(signals, key=lambda s: s[2])

        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=sig, conviction=conv,
            rationale=reason,
            factors={"active_patterns": [s[0] for s in signals]},
        )

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


magus = Magus()



================================================
FILE: silmaril/agents/midas.py
================================================
[Binary file]


================================================
FILE: silmaril/agents/nightshade.py
================================================
"""
silmaril.agents.nightshade — The Insider Watcher.

NIGHTSHADE only watches one thing: SEC Form 4 filings. When 3+ company
insiders buy in a 30-day window with no offsetting sales, that's a
cluster signal. Same logic in reverse for sells.

Wired-upstream fields (optional on AssetContext):
  - insider_buys_30d:   int, count of insider buys last 30 days
  - insider_sells_30d:  int, count of insider sells last 30 days
  - insider_net_dollars_30d: float, net dollar value (buys - sells)

If these fields aren't present on the context, NIGHTSHADE abstains
gracefully — no false signals from missing data.
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Nightshade(Agent):
    codename = "NIGHTSHADE"
    specialty = "Form 4 Insider Cluster Detection"
    temperament = (
        "Patient, watches the executives. Believes the people closest "
        "to the books know things the market doesn't yet. Stays silent "
        "until cluster activity is unambiguous."
    )
    inspiration = "The deadly nightshade — quiet, watchful, decisive"
    asset_classes = ("equity",)

    def _judge(self, ctx: AssetContext) -> Verdict:
        buys = getattr(ctx, "insider_buys_30d", None)
        sells = getattr(ctx, "insider_sells_30d", None)
        net = getattr(ctx, "insider_net_dollars_30d", None)

        # If no insider data wired in, abstain rather than guess
        if buys is None and sells is None:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale="no insider transaction data available",
                factors={"data_missing": True},
            )

        buys = buys or 0
        sells = sells or 0
        factors = {"buys_30d": buys, "sells_30d": sells}
        if net is not None:
            factors["net_dollars_30d"] = net

        # Strong cluster buy
        if buys >= 3 and sells == 0:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.STRONG_BUY,
                conviction=min(0.85, 0.55 + 0.08 * buys),
                rationale=f"{buys} insider buys, 0 sells in 30d — strong cluster",
                factors=factors,
            )

        # Mild cluster buy
        if buys >= 2 and sells <= 1:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.BUY,
                conviction=0.55,
                rationale=f"{buys} insider buys vs {sells} sells in 30d",
                factors=factors,
            )

        # Cluster sell
        if sells >= 3 and buys == 0:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.SELL,
                conviction=0.55,
                rationale=f"{sells} insider sells, 0 buys in 30d — distribution",
                factors=factors,
            )

        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=Signal.HOLD,
            conviction=0.0,
            rationale=f"no decisive insider cluster ({buys}b/{sells}s)",
            factors=factors,
        )


nightshade = Nightshade()



================================================
FILE: silmaril/agents/nomad.py
================================================
"""
silmaril.agents.nomad — The ADR Arbitrageur.

NOMAD watches the same company in two cities. When the US ADR drifts
more than 2% from the home listing, that's pure arbitrage — short the
rich side, buy the cheap. Currency-adjusted, of course, but the core
spread above 2% is meaningful in liquid pairs.

Currently the SILMARIL universe doesn't carry foreign listings, so
NOMAD will abstain on everything by default. The logic is in place for
the day a foreign listing feed is wired in.

Optional upstream field:
  - adr_local_spread_pct: float, (ADR_price - home_price_USD) / home_price_USD
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


# US ADR → home listing pairs (for documentation)
ADR_PAIRS = {
    "BABA": "9988.HK", "TSM": "2330.TW", "SHEL": "SHEL.L", "NVO": "NOVO-B.CO",
    "AZN": "AZN.L", "GSK": "GSK.L", "HSBC": "HSBA.L", "TM": "7203.T",
    "SONY": "6758.T", "NIO": "9866.HK", "BIDU": "9888.HK",
}


class Nomad(Agent):
    codename = "NOMAD"
    specialty = "ADR / Home Listing Arbitrage"
    temperament = (
        "Sees the same asset trade at different prices in different "
        "cities. Doesn't predict — just notices. When the spread is "
        "real, takes the cheap side, sells the rich side, lets the "
        "world re-converge."
    )
    inspiration = "The nomad — at home in two places, tied to neither"
    asset_classes = ("equity",)

    def applies_to(self, ctx: AssetContext) -> bool:
        if ctx.ticker not in ADR_PAIRS:
            return False
        return getattr(ctx, "adr_local_spread_pct", None) is not None

    def _judge(self, ctx: AssetContext) -> Verdict:
        spread = getattr(ctx, "adr_local_spread_pct", 0.0) or 0.0

        if spread >= 0.02:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.SELL,
                conviction=0.60,
                rationale=f"ADR trades {spread:+.1%} above home — overpriced vs home",
                factors={"adr_spread": spread},
            )
        if spread <= -0.02:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.BUY,
                conviction=0.60,
                rationale=f"ADR trades {spread:+.1%} below home — underpriced vs home",
                factors={"adr_spread": spread},
            )

        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=Signal.HOLD,
            conviction=0.0,
            rationale=f"ADR spread {spread:+.1%} inside arb threshold",
            factors={"adr_spread": spread},
        )


nomad = Nomad()



================================================
FILE: silmaril/agents/obsidian.py
================================================
"""
silmaril.agents.obsidian — The Resource King.

OBSIDIAN evaluates only commodities and resource-related assets: gold,
oil, silver, copper, natural gas, energy ETFs, materials. Its lens is
scarcity, inflation, and sovereign positioning.

v2.0 changes — backtest revealed OBSIDIAN was 45.5% win rate. The old
logic was "buy commodity uptrends, sell commodity downtrends," but
commodities are notoriously mean-reverting on intermediate timeframes.
A trend-following stance loses systematically because it buys near tops
and sells near bottoms. The fix:
  - On the BUY side: require RSI < 60 (don't buy near overbought tops).
  - On the SELL side: require RSI > 65 AND a real trend break,
    not just any "below both SMAs" condition.
  - Added an explicit MEAN-REVERT BUY: deep oversold (RSI < 30) on
    a commodity is historically a high-quality entry.

Black Panther's archetype: wealth drawn from the earth itself.
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


OBSIDIAN_UNIVERSE = {
    "XLE", "XLB",
    "GLD", "SLV", "USO", "UNG",
    "DBC", "CPER",
    "XOM", "CVX", "COP", "SLB",
    "FCX", "NEM", "GOLD",
}


class Obsidian(Agent):
    codename = "OBSIDIAN"
    specialty = "Commodities & Resources"
    temperament = "Patient hoarder of hard assets. Bets on scarcity and mean-reversion in commodities."
    inspiration = "Black Panther — the wealth drawn from the earth"
    asset_classes = ("equity", "etf")

    DEEP_OVERSOLD = 30
    DEEP_OVERBOUGHT = 70
    BUY_RSI_CEILING = 60
    SELL_RSI_FLOOR = 65

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker.upper() in OBSIDIAN_UNIVERSE or ctx.sector in {"Energy", "Materials", "Commodities"}

    def _judge(self, ctx: AssetContext) -> Verdict:
        if not ctx.price or not ctx.sma_50 or not ctx.sma_200:
            return self._hold(ctx, "insufficient data for commodity thesis")

        rsi = ctx.rsi_14 or 50
        sent = ctx.sentiment_score or 0
        sent_available = ctx.sentiment_score is not None
        trend_up = ctx.price > ctx.sma_50 and ctx.sma_50 > ctx.sma_200
        trend_down = ctx.price < ctx.sma_50 and ctx.sma_50 < ctx.sma_200

        # ── Deep oversold mean-reversion BUY (highest priority) ──
        if rsi < self.DEEP_OVERSOLD:
            entry = ctx.price
            stop = ctx.price * 0.94
            target = ctx.price * 1.10
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.65,
                rationale=f"Commodity deep oversold (RSI {rsi:.0f}) — mean-reversion entry.",
                factors={"rsi": round(rsi, 1), "mode": "mean_revert"},
                suggested_entry=round(entry, 2),
                suggested_stop=round(stop, 2),
                suggested_target=round(target, 2),
                invalidation="Break below recent lows invalidates the bounce thesis.",
            )

        # ── Trend-following BUY (only on healthy trend, not stretched) ──
        sentiment_ok = (not sent_available) or (sent >= 0)
        if trend_up and rsi < self.BUY_RSI_CEILING and sentiment_ok:
            conv = 0.55 + (sent * 0.15 if sent_available else 0)
            entry = ctx.price
            stop = ctx.price * 0.95
            target = ctx.price * 1.10
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=self._clamp(conv),
                rationale=f"Commodity uptrend, RSI {rsi:.0f} not stretched — momentum continuation.",
                factors={"trend": "up", "rsi": round(rsi, 1), "mode": "trend"},
                suggested_entry=round(entry, 2),
                suggested_stop=round(stop, 2),
                suggested_target=round(target, 2),
                invalidation="Close below SMA-50 breaks the uptrend thesis.",
            )

        # ── Mean-revert SELL: deeply overbought regardless of trend ──
        if rsi > self.DEEP_OVERBOUGHT:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.55,
                rationale=f"Commodity overbought (RSI {rsi:.0f}) — mean-reversion sell.",
                factors={"rsi": round(rsi, 1), "mode": "mean_revert"},
            )

        # ── Trend-following SELL (much more selective now) ──
        if trend_down and rsi > self.SELL_RSI_FLOOR:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.5,
                rationale=f"Commodity downtrend with RSI bounce (RSI {rsi:.0f}) — sell rallies.",
                factors={"trend": "down", "rsi": round(rsi, 1)},
            )

        return self._hold(ctx, f"commodity in transition (RSI {rsi:.0f}) — no edge")

    def _hold(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.HOLD, conviction=0.3, rationale=reason,
        )


obsidian = Obsidian()



================================================
FILE: silmaril/agents/scrooge.py
================================================
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


STARTING_CAPITAL = 10.00  # $10 starting capital
REINCARNATION_THRESHOLD = 0.50  # Below $0.50 = reset


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

    # ── Determine today's pick FIRST so we can decide whether to rotate ─
    next_pick = _pick_best_buy(top_consensus)

    # ── Step 0: Fee-aware rotation gate ──────────────────────────
    # If SCROOGE already holds something AND the new pick isn't significantly
    # better than what he holds (after round-trip fees), HODL instead.
    if state.current_position and next_pick:
        from .fee_aware_rotation import should_rotate
        held_ticker = state.current_position["ticker"]
        target_ticker = next_pick["ticker"]
        target_price = prices.get(target_ticker, 0)

        # Find the held ticker's current consensus from the same list (if present)
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
            # Same pick — pure HODL, no rotation, no fees
            state.history.append({
                "date": today,
                "action": "HODL",
                "ticker": held_ticker,
                "reason": "Top pick unchanged. SCROOGE holds, avoids round-trip fees.",
                "life": state.current_life,
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
            multiplier=2.0,  # SCROOGE is patient
        )
        if not rotate:
            state.history.append({
                "date": today,
                "action": "HODL",
                "ticker": held_ticker,
                "reason": why,
                "life": state.current_life,
            })
            return state

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



================================================
FILE: silmaril/agents/shepherd.py
================================================
"""
silmaril.agents.shepherd — The Bond Yield Watcher.

SHEPHERD watches the 10-year Treasury yield and rotates between bonds
and rate-sensitive sectors. When 10Y rises fast, rate-sensitives squeeze
and duration sells off. When yields ease, the same sectors catch a bid.

v2.0 changes — backtest revealed 46.6% win rate. The original 25bps
trigger was too loose (fires on roughly 1/3 of all 5-day windows).
Tightened to 35bps. Added an RSI mean-revert path on bond ETFs because
they tend to mean-revert intraweek.
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


BONDS = {"TLT", "IEF", "SHY", "AGG", "BND", "HYG", "LQD", "MUB", "TIP", "VTEB"}
RATE_SENSITIVE = {"XLU", "IYR", "VNQ", "XLP", "XLRE"}
SHEPHERD_UNIVERSE = BONDS | RATE_SENSITIVE


class Shepherd(Agent):
    codename = "SHEPHERD"
    specialty = "Bond & Rate-Sensitive Sector Specialist"
    temperament = (
        "Methodical, watches the long end. When the 10Y moves fast, "
        "the rate-sensitive flock scatters — SHEPHERD calls them home "
        "before the move completes."
    )
    inspiration = "The shepherd — moves the flock before the storm hits"
    asset_classes = ("etf",)

    YIELD_SPIKE_BPS = 35      # was 25, too loose
    EXTREME_VIX = 30
    BOND_OVERSOLD_RSI = 30
    BOND_OVERBOUGHT_RSI = 72

    def applies_to(self, ctx: AssetContext) -> bool:
        return ctx.ticker in SHEPHERD_UNIVERSE

    def _judge(self, ctx: AssetContext) -> Verdict:
        tnx_5d = getattr(ctx, "tnx_change_5d_bps", None)
        regime = ctx.market_regime
        vix = ctx.vix
        rsi = ctx.rsi_14 or 50

        # ── Yield-driven trades (highest priority) ──
        if tnx_5d is not None:
            if tnx_5d >= self.YIELD_SPIKE_BPS and ctx.ticker in BONDS:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.60,
                    rationale=f"10Y +{tnx_5d:.0f}bp/5d → bonds oversold, mean-revert.",
                    factors={"tnx_change_5d_bps": tnx_5d},
                )
            if tnx_5d >= self.YIELD_SPIKE_BPS and ctx.ticker in RATE_SENSITIVE:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.SELL, conviction=0.55,
                    rationale=f"10Y +{tnx_5d:.0f}bp/5d → rate-sensitives squeezed.",
                    factors={"tnx_change_5d_bps": tnx_5d},
                )
            if tnx_5d <= -self.YIELD_SPIKE_BPS and ctx.ticker in RATE_SENSITIVE:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.55,
                    rationale=f"10Y {tnx_5d:.0f}bp/5d → rate-sensitive tailwind.",
                    factors={"tnx_change_5d_bps": tnx_5d},
                )

        # ── Mean-revert on bond ETFs by RSI ──
        if ctx.ticker in BONDS:
            if rsi < self.BOND_OVERSOLD_RSI:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.55,
                    rationale=f"Bond {ctx.ticker} oversold (RSI {rsi:.0f}) — mean-revert.",
                    factors={"rsi": rsi, "mode": "mean_revert"},
                )
            if rsi > self.BOND_OVERBOUGHT_RSI:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.SELL, conviction=0.50,
                    rationale=f"Bond {ctx.ticker} overbought (RSI {rsi:.0f}) — mean-revert.",
                    factors={"rsi": rsi, "mode": "mean_revert"},
                )

        # ── Regime fallback ──
        if regime == "RISK_OFF" and ctx.ticker in BONDS:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.50,
                rationale="Risk-off → duration tailwind.",
                factors={"regime": regime},
            )
        if vix and vix >= self.EXTREME_VIX and ctx.ticker in BONDS:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.50,
                rationale=f"VIX {vix:.0f} → flight-to-quality bid.",
                factors={"vix": vix},
            )

        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.HOLD, conviction=0.0,
            rationale="rate signal not decisive",
        )


shepherd = Shepherd()



================================================
FILE: silmaril/agents/short_alpha.py
================================================
"""
silmaril.agents.short_alpha — Daily-move short specialist.

The user requested: "an agent specifically designed for short trading that
can capitalize on daily market movements... analyze headlines, social media
posts, and other relevant information to identify minor trades that can
yield significant profits from small investments."

Honest design notes:
  - Retail short-selling has structural disadvantages: short-borrow costs,
    short-squeeze risk, asymmetric loss profile (unbounded upside).
  - The defensible edge is news-driven catalysts on liquid large-caps:
      * Earnings miss with guidance cut
      * FDA rejection / regulatory action
      * Major customer loss / contract termination
      * CFO sudden departure (high specificity historical signal)
      * Credible short report (Hindenburg, Citron, Muddy Waters)
      * Technical breakdown (gap-down on 3x volume below key support)
  - We avoid:
      * Small-cap shorts (squeeze risk)
      * Retail-favorite memestocks (gamma squeeze risk)
      * Names with high short-interest already (crowded short = squeeze fuel)
  - Risk controls:
      * 1-3 day horizon (daily moves, not deep shorts)
      * Hard stop at +3% above entry
      * Position cap 1-2% per name, 5% portfolio max
      * Trade size scales with conviction × news quality
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


# Negative-catalyst keywords with rough impact weights
NEGATIVE_CATALYSTS = {
    "miss":                    0.35, "missed":                    0.35,
    "guidance cut":            0.55, "lowered guidance":          0.55,
    "withdrew guidance":       0.55, "suspends guidance":         0.55,
    "downgrade":               0.30, "downgraded":                0.30,
    "fraud":                   0.80, "investigation":             0.55,
    "subpoena":                0.55, "sec probe":                 0.60,
    "fda rejection":           0.70, "complete response letter":  0.70,
    "recall":                  0.45, "lawsuit":                   0.30,
    "cfo resigns":             0.50, "cfo departure":             0.50,
    "ceo resigns":             0.45, "stepping down":             0.30,
    "going concern":           0.85, "bankruptcy":                0.95,
    "delisting":               0.85, "restate":                   0.65,
    "cyberattack":             0.40, "data breach":               0.40,
    "short report":            0.50, "hindenburg":                0.55,
    "citron":                  0.45, "muddy waters":              0.50,
    "contract terminated":     0.45, "lost contract":             0.40,
    "plant closure":           0.35, "layoffs":                   0.20,
    "delay":                   0.25, "delayed":                   0.25,
    "warning":                 0.30, "weak quarter":              0.40,
}


# Squeeze-risk filter — these tickers have heightened gamma squeeze potential
SQUEEZE_RISK_BLACKLIST = {
    "GME", "AMC", "BBBY", "BB", "KOSS", "EXPR",
    # Names with chronic high short interest + retail favorability
}


class ShortAlpha(Agent):
    codename = "SHORT_ALPHA"
    specialty = "News-Driven Daily Shorts"
    temperament = (
        "Predatory and disciplined. Hunts catalyst-driven daily moves on "
        "liquid large-caps. Refuses to short illiquid small-caps or "
        "memestocks where squeeze risk is asymmetric. Closes within 1-3 "
        "days regardless of P&L — never married to a thesis."
    )

    # Liquid large-caps only. Conservative starting universe.
    UNIVERSE_TICKERS = {
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC",
        "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK",
        "XOM", "CVX", "COP", "OXY",
        "JNJ", "UNH", "PFE", "MRK", "ABBV", "LLY", "BMY", "GILD",
        "WMT", "TGT", "HD", "LOW", "COST", "NKE", "MCD",
        "DIS", "NFLX", "CRM", "ORCL", "ADBE", "CSCO",
        "SPY", "QQQ", "IWM", "DIA",
        "XLF", "XLE", "XLK", "XLV", "XLY", "XLP",
        # Major crypto where shorting via inverse ETFs / Alpaca shortable
        "COIN", "MSTR",
    }

    def _judge(self, ctx: AssetContext) -> Verdict:
        if ctx.ticker in SQUEEZE_RISK_BLACKLIST:
            return Verdict(
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale="Squeeze-risk blacklist — no short on retail-meme names",
            )

        if ctx.ticker not in self.UNIVERSE_TICKERS:
            return Verdict(
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale="Outside SHORT_ALPHA liquid-large-cap universe",
            )

        # ---- 1. Negative catalyst detection ----
        catalyst_score = 0.0
        matched_catalysts = []
        headlines = self._collect_headlines(ctx)
        combined = " ".join(headlines).lower()

        for keyword, weight in NEGATIVE_CATALYSTS.items():
            if keyword in combined:
                catalyst_score += weight
                matched_catalysts.append(keyword)

        catalyst_score = min(1.0, catalyst_score)

        # ---- 2. Sentiment confirmation ----
        sentiment = getattr(ctx, "sentiment_score", 0) or 0
        sentiment_negative = sentiment < -0.20

        # ---- 3. Technical breakdown check ----
        price = ctx.price or 0
        sma_20 = getattr(ctx, "sma_20", None)
        sma_50 = getattr(ctx, "sma_50", None)
        change_pct = getattr(ctx, "change_pct", 0) or 0
        volume = getattr(ctx, "volume", 0) or 0
        avg_vol = getattr(ctx, "avg_volume_30d", 0) or 0

        breakdown = False
        breakdown_reasons = []
        if sma_20 and price < sma_20 * 0.99:
            breakdown_reasons.append("below SMA-20")
            breakdown = True
        if sma_50 and price < sma_50 * 0.98:
            breakdown_reasons.append("below SMA-50")
            breakdown = True
        if change_pct < -2.0 and avg_vol > 0 and volume > avg_vol * 1.5:
            breakdown_reasons.append(f"-{abs(change_pct):.1f}% on {volume/avg_vol:.1f}x volume")
            breakdown = True

        # ---- 4. Decision logic ----
        # STRONG_SELL: catalyst > 0.5 AND (sentiment OR breakdown)
        # SELL:        catalyst > 0.3 AND breakdown, OR catalyst > 0.4 AND sentiment
        # HOLD:        catalyst < 0.3 OR no confirmation
        # ABSTAIN:     no catalyst at all (no signal to act on)

        if catalyst_score == 0 and not breakdown:
            return Verdict(
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale="No negative catalyst, no technical breakdown — no setup",
            )

        if catalyst_score >= 0.55 and (sentiment_negative or breakdown):
            conviction = min(0.85, 0.40 + catalyst_score * 0.5)
            rationale = (
                f"STRONG_SELL setup — catalysts: {', '.join(matched_catalysts[:3])}. "
                f"{'Negative sentiment + ' if sentiment_negative else ''}"
                f"{'Technical breakdown: ' + ', '.join(breakdown_reasons[:2]) if breakdown else ''}. "
                f"Target: -3% in 1-3 days. Hard stop at +3%."
            )
            return Verdict(
                signal=Signal.STRONG_SELL,
                conviction=conviction,
                rationale=rationale,
            )

        if (catalyst_score >= 0.30 and breakdown) or \
           (catalyst_score >= 0.40 and sentiment_negative):
            conviction = min(0.65, 0.35 + catalyst_score * 0.3)
            rationale = (
                f"SELL setup — catalysts: {', '.join(matched_catalysts[:3]) or 'none'}. "
                f"{'Sentiment negative. ' if sentiment_negative else ''}"
                f"{'Breakdown: ' + ', '.join(breakdown_reasons[:2]) if breakdown else ''}"
            )
            return Verdict(
                signal=Signal.SELL,
                conviction=conviction,
                rationale=rationale,
            )

        if breakdown and catalyst_score < 0.20:
            return Verdict(
                signal=Signal.HOLD,
                conviction=0.40,
                rationale=(
                    f"Technical breakdown without catalyst confirmation. "
                    f"Wait for headline trigger before entering short."
                ),
            )

        return Verdict(
            signal=Signal.HOLD,
            conviction=0.25,
            rationale=(
                f"Catalyst score {catalyst_score:.2f} but missing confirmation. "
                f"Need sentiment or technical breakdown to short."
            ),
        )

    def _collect_headlines(self, ctx: AssetContext) -> list:
        headlines = []
        # Try multiple field names — backward compat with older AssetContext
        for field_name in ("headlines", "news_headlines", "recent_headlines"):
            v = getattr(ctx, field_name, None)
            if isinstance(v, list):
                headlines.extend(str(h) for h in v if h)
        # Also pull from news items if present
        items = getattr(ctx, "news_items", None)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    h = item.get("headline") or item.get("title") or ""
                    if h:
                        headlines.append(str(h))
        return headlines



================================================
FILE: silmaril/agents/speck.py
================================================
"""
silmaril.agents.speck — The Small Thing.

SPECK specializes in what the big agents ignore: small-caps (IWM),
lower-profile sector ETFs, and equities with low article counts. Its
edge is that institutional flows take longer to move small things —
so news that fires a setup can lead price by days, not hours.

Ant-Man's archetype: tiny scale, outsized leverage.

Decision logic:
  - Only evaluates IWM, ARKK, and equities with low mega-cap profile
  - Low article count (< 4) + positive sentiment + price above SMA-50 → BUY
  - High RSI on small-cap name → caution
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


SPECK_UNIVERSE = {"IWM", "ARKK"}
MEGA_CAPS = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    "BRK-B", "JPM", "V", "MA", "JNJ", "UNH", "LLY", "XOM", "CVX",
    "HD", "PG", "KO", "WMT", "COST",
}


class Speck(Agent):
    codename = "SPECK"
    specialty = "Small-Cap & Overlooked"
    temperament = "Tiny scale, outsized leverage. Reads news that big agents dismiss."
    inspiration = "Ant-Man — small is fast"
    asset_classes = ("equity", "etf")

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker.upper() in SPECK_UNIVERSE or ctx.ticker.upper() not in MEGA_CAPS

    def _judge(self, ctx: AssetContext) -> Verdict:
        # SPECK likes when nobody's watching
        if ctx.article_count > 8:
            return self._abstain(ctx, "too much coverage — not a SPECK setup")

        if not ctx.price or not ctx.sma_50:
            return self._abstain(ctx, "need basic trend data")

        trend_ok = ctx.price > ctx.sma_50
        sent = ctx.sentiment_score or 0

        if trend_ok and sent > 0.1 and ctx.article_count >= 1:
            conv = 0.52 + min(sent * 0.3, 0.2)
            entry = ctx.price
            stop = ctx.sma_50
            target = ctx.price + (ctx.price - stop) * 2.5
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=self._clamp(conv),
                rationale=(
                    f"Low coverage ({ctx.article_count} articles) but sentiment {sent:+.2f} "
                    f"and price above SMA-50 — small edge before crowd arrives."
                ),
                factors={"article_count": ctx.article_count, "sentiment": round(sent, 3)},
                suggested_entry=round(entry, 2),
                suggested_stop=round(stop, 2),
                suggested_target=round(target, 2),
                invalidation=f"Close below SMA-50 (${stop:.2f}) or mega-cap-level news coverage.",
            )

        return self._abstain(ctx, "no small-cap edge today")

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


speck = Speck()



================================================
FILE: silmaril/agents/sports_bro.py
================================================
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
        "label": market.get("label") or market.get("title") or market.get("market"),
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
    # BUG 3 FIX: capture real UTC timestamp once, use it in all history entries
    ts = datetime.now(timezone.utc).isoformat()

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
            "timestamp": ts,
            "action": "REINCARNATION",
            "life": state.current_life,
        })

    # Cap daily trades
    if state.trades_today >= MAX_TRADES_PER_DAY:
        state.history.append({
            "date": today,
            "timestamp": ts,
            "action": "HOLD",
            "reason": f"Daily trade cap ({MAX_TRADES_PER_DAY}) reached.",
            "balance": round(state.balance, 4),
        })
        return state

    # If already holding an open bet, don't stack another
    if state.open_bets:
        state.history.append({
            "date": today,
            "timestamp": ts,
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
            "timestamp": ts,
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
        "timestamp": ts,
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



================================================
FILE: silmaril/agents/steadfast.py
================================================
"""
silmaril.agents.steadfast — STEADFAST, the blue-chip patriot.

The agent your grandfather would approve of. Buys only from the
"Crown Jewels" — long-standing American blue chips with dividend
histories and household-name moats. Holds for a minimum of 30 days.
Lectures the rest of the cohort about discipline and patience.

Plays:
  - Dividend payers with 25+ year track records
  - Defensive consumer staples (KO, PG, JNJ, PEP)
  - American institutional brands (DIS, MCD, WMT, HD)
  - Industrials with century-long histories (CAT, MMM, GE, BA)
  - Pharma & healthcare quality (PFE, MRK, JNJ, ABBV)
  - Banks with dividend reliability (JPM, BAC, BRK-B)
  - Energy majors when they yield (XOM, CVX)
  - Telecoms when valuations rationalize (T, VZ)
  - Tobacco when nobody wants it (MO)

Refuses to buy:
  - Anything without a 10+ year dividend history (excl. AAPL grandfathered in)
  - Crypto (obviously)
  - Tech speculative
  - Foreign-listed
  - Biotech without a marketed product

STEADFAST does not get excited. STEADFAST gets paid quarterly.
"""

from __future__ import annotations

from typing import Optional

from .base import Agent, AssetContext, Signal, Verdict


# The "Crown Jewels" — STEADFAST's permitted buy universe.
# Curated to American institutional blue chips with long track records.
CROWN_JEWELS = {
    # Consumer Staples
    "KO":   "Coca-Cola",
    "PEP":  "PepsiCo",
    "PG":   "Procter & Gamble",
    "JNJ":  "Johnson & Johnson",
    "WMT":  "Walmart",
    "COST": "Costco",
    "MO":   "Altria",
    "PM":   "Philip Morris",
    "CL":   "Colgate-Palmolive",
    # Consumer Discretionary
    "MCD":  "McDonald's",
    "DIS":  "Disney",
    "HD":   "Home Depot",
    "LOW":  "Lowe's",
    "NKE":  "Nike",
    "SBUX": "Starbucks",
    # Industrials
    "CAT":  "Caterpillar",
    "MMM":  "3M",
    "GE":   "General Electric",
    "BA":   "Boeing",
    "DE":   "Deere",
    "HON":  "Honeywell",
    "F":    "Ford",
    "GM":   "General Motors",
    # Energy majors (only when yielding)
    "XOM":  "Exxon Mobil",
    "CVX":  "Chevron",
    # Healthcare / Pharma
    "PFE":  "Pfizer",
    "MRK":  "Merck",
    "ABBV": "AbbVie",
    "BMY":  "Bristol-Myers Squibb",
    "LLY":  "Eli Lilly",
    "UNH":  "UnitedHealth",
    # Financials
    "JPM":  "JPMorgan Chase",
    "BAC":  "Bank of America",
    "WFC":  "Wells Fargo",
    "BRK-B": "Berkshire Hathaway",
    "V":    "Visa",
    "MA":   "Mastercard",
    # Telecom
    "T":    "AT&T",
    "VZ":   "Verizon",
    # Utilities
    "DUK":  "Duke Energy",
    "SO":   "Southern Company",
    "NEE":  "NextEra Energy",
    # Grandfathered tech (long enough history for STEADFAST)
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "IBM":  "IBM",
}

MINIMUM_HOLD_DAYS = 30


class Steadfast(Agent):
    codename = "STEADFAST"
    specialty = "American blue-chip dividend payers"
    temperament = "Patient. Skeptical of hype. Quarterly-dividend pace."
    inspiration = "Your grandfather, who bought IBM in 1962 and never sold"
    asset_classes = ("equity",)

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker.upper() in CROWN_JEWELS

    def _judge(self, ctx: AssetContext) -> Verdict:
        ticker = ctx.ticker.upper()
        chg = ctx.change_pct or 0.0
        sent = ctx.sentiment_score or 0.0
        price = ctx.price or 0.0
        sma_200 = getattr(ctx, "sma_200", None)
        rsi = getattr(ctx, "rsi_14", None)

        name = CROWN_JEWELS.get(ticker, ticker)

        # ── STEADFAST's rules ─
        # Buy on dips (below 200-day SMA or RSI < 40), with long-term sentiment OK
        below_sma = sma_200 and price < sma_200 * 0.98
        oversold = rsi and rsi < 40
        very_negative_news = sent < -0.4

        if very_negative_news:
            # Even crown jewels can crack — STEADFAST waits when sentiment is awful
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.HOLD, conviction=0.5,
                rationale=(f"Even {name} can have a bad quarter. Sentiment is "
                           f"sharply negative. STEADFAST waits for the dust to settle "
                           f"rather than catching a falling knife on principle."),
            )

        if (below_sma or oversold) and sent > -0.2:
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.BUY, conviction=0.7,
                rationale=(f"STEADFAST sees value in {name}. Quality compounds. "
                           f"This is what your grandfather would've bought. "
                           f"Hold for the dividend, not for the candle."),
            )

        if chg > 5.0:
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.HOLD, conviction=0.4,
                rationale=(f"{name} ran {chg:+.1f}% today. STEADFAST does not chase. "
                           f"Quality compounds; chasing rarely does."),
            )

        if chg < -3.0 and sent > -0.3:
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.BUY, conviction=0.6,
                rationale=(f"{name} -{abs(chg):.1f}% on no fundamental change. "
                           f"STEADFAST adds to quality on weakness. "
                           f"You buy umbrellas when it rains."),
            )

        if sent > 0.3 and chg > 0.5:
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.BUY, conviction=0.55,
                rationale=(f"Constructive backdrop on {name}. STEADFAST initiates "
                           f"or adds. Slow and steady wins the race."),
            )

        return Verdict(
            agent=self.codename, ticker=ticker,
            signal=Signal.HOLD, conviction=0.4,
            rationale=(f"{name} in equilibrium. STEADFAST is patient. "
                       f"He'd rather miss a 5% rally than chase one."),
        )


steadfast = Steadfast()



================================================
FILE: silmaril/agents/synth.py
================================================
"""
silmaril.agents.synth — The Synthesist.

SYNTH looks across markets for correlation and rotation signals. Its
edge is reading what's moving with what — and what isn't. Vision's
archetype: synthetic perception across systems.

v2.0 changes — backtest revealed SYNTH was 50.1% win rate. The old
logic only voted on RISK_ON or RISK_OFF regimes, abstaining on
NEUTRAL. But the regime classifier produces NEUTRAL roughly half
the time, so SYNTH was sitting out half the market. Fixed by:
  - Adding NEUTRAL-regime logic: bias slightly defensive when VIX is
    elevated (>20) even in NEUTRAL, slightly long-cyclical when calm.
  - Tightening BUY conditions: requires sentiment >= 0 OR sentiment
    unavailable AND momentum positive.
  - SELL conditions now also require some technical confirmation, not
    just regime tag.
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


MACRO_DEFENSIVES = {"XLP", "XLU", "XLV", "GLD", "SLV", "TLT"}
MACRO_RISK = {"SPY", "QQQ", "IWM", "XLK", "XLY", "XLF"}


class Synth(Agent):
    codename = "SYNTH"
    specialty = "Cross-Market Correlation"
    temperament = "Synthesizes signals across markets. Reads the rotation the crowd misses."
    inspiration = "Vision — synthetic perception across systems"
    asset_classes = ("equity", "etf")

    def _judge(self, ctx: AssetContext) -> Verdict:
        regime = ctx.market_regime
        sent = ctx.sentiment_score or 0
        sent_available = ctx.sentiment_score is not None
        vix = ctx.vix or 18.0

        is_defensive = (
            ctx.ticker.upper() in MACRO_DEFENSIVES
            or ctx.sector in {"Staples", "Utilities", "Healthcare"}
        )
        is_risk = (
            ctx.ticker.upper() in MACRO_RISK
            or ctx.sector in {"Technology", "Discretionary"}
        )

        if not (is_defensive or is_risk):
            return self._abstain(ctx, "not in cross-market rotation universe")

        # Compute short momentum signal
        ph = ctx.price_history or []
        mom_10d = None
        if len(ph) >= 11 and ph[-11] > 0:
            mom_10d = (ctx.price / ph[-11]) - 1.0

        # ── RISK_OFF regime ──────────────────────────────────────
        if regime == "RISK_OFF":
            if is_defensive:
                conv = 0.60 + min(vix - 25, 5) * 0.01 if vix > 25 else 0.55
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=self._clamp(conv),
                    rationale=f"Risk-off regime, VIX {vix:.0f} — defensive rotation.",
                    factors={"regime": regime, "vix": vix},
                )
            if is_risk and (mom_10d is None or mom_10d <= 0):
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.SELL, conviction=0.55,
                    rationale="Risk-off regime — reducing cyclical exposure.",
                    factors={"regime": regime},
                )

        # ── RISK_ON regime ────────────────────────────────────────
        if regime == "RISK_ON":
            sent_ok = (not sent_available) or (sent >= 0)
            if is_risk and sent_ok and (mom_10d is None or mom_10d >= 0):
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.55,
                    rationale="Risk-on regime supports cyclical exposure.",
                    factors={"regime": regime},
                )

        # ── NEUTRAL regime: VIX-tilted ────────────────────────────
        if regime == "NEUTRAL":
            if vix >= 22 and is_defensive:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.50,
                    rationale=f"Neutral regime but VIX {vix:.0f} elevated — defensive lean.",
                    factors={"regime": regime, "vix": vix},
                )
            if vix < 16 and is_risk and (mom_10d is None or mom_10d > 0):
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.45,
                    rationale=f"Neutral regime, VIX {vix:.0f} calm — cyclical lean.",
                    factors={"regime": regime, "vix": vix},
                )

        return self._abstain(ctx, f"regime {regime} — no cross-market edge")

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


synth = Synth()



================================================
FILE: silmaril/agents/talon.py
================================================
"""
silmaril.agents.talon — The Overhead View.

TALON only evaluates the broad indices: SPY, QQQ, IWM, DIA, VTI. Its
lens is market structure — regime, breadth, breakout vs. breakdown at
the index level. Falcon's archetype: aerial perspective.

v2.0 changes — backtest revealed TALON was 50.3% win rate (basically
a coin flip). The old logic voted BUY whenever indices were above both
SMAs, which is most of the time, and voted SELL whenever they were
below SMA-200. Both signals fire in choppy markets and lose. Fixed by:
  - Requiring momentum confirmation (20-day price rise) for BUY
  - Tightening SELL trigger: needs both below SMA-200 AND 20-day
    momentum negative AND VIX elevated
  - Adding ABSTAIN on transition zones instead of forcing HOLD
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


INDEX_TICKERS = {"SPY", "QQQ", "DIA", "IWM", "VTI"}


class Talon(Agent):
    codename = "TALON"
    specialty = "Market Structure"
    temperament = "Aerial view. Evaluates only the indices. Market shape, not individual names."
    inspiration = "Falcon — the overhead view"
    asset_classes = ("etf",)

    MIN_MOMENTUM_BUY = 0.02      # 2% over 20 days for momentum confirmation
    MAX_MOMENTUM_SELL = -0.03    # -3% over 20 days for breakdown confirmation
    PANIC_VIX = 25.0

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker.upper() in INDEX_TICKERS

    def _judge(self, ctx: AssetContext) -> Verdict:
        if not ctx.price or not ctx.sma_50 or not ctx.sma_200:
            return self._abstain(ctx, "insufficient index structure data")

        ph = ctx.price_history or []
        mom_20d = None
        if len(ph) >= 21 and ph[-21] > 0:
            mom_20d = (ctx.price / ph[-21]) - 1.0

        above_200 = ctx.price > ctx.sma_200
        above_50 = ctx.price > ctx.sma_50
        stack_up = ctx.sma_50 > ctx.sma_200
        vix = ctx.vix or 18.0

        # ── BUY: requires positive momentum confirmation ──
        if (
            above_200 and above_50 and stack_up
            and mom_20d is not None and mom_20d >= self.MIN_MOMENTUM_BUY
            and vix < 22
        ):
            conv = 0.55 + min(mom_20d * 2, 0.15)  # bonus if momentum strong
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=self._clamp(conv),
                rationale=(
                    f"Index structure intact: above both SMAs, 20d momentum "
                    f"{mom_20d*100:+.1f}%, VIX {vix:.1f} calm — risk-on."
                ),
                factors={"momentum_20d": round(mom_20d, 4), "vix": vix},
                suggested_entry=ctx.price,
                suggested_stop=round(ctx.sma_50, 2),
                suggested_target=round(ctx.price * 1.06, 2),
                invalidation="Close below SMA-50 invalidates the structure thesis.",
            )

        # ── SELL: requires structural breakdown + confirmation ──
        if (
            not above_200
            and mom_20d is not None and mom_20d <= self.MAX_MOMENTUM_SELL
            and vix >= self.PANIC_VIX
        ):
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.60,
                rationale=(
                    f"Index broken: below SMA-200, 20d momentum {mom_20d*100:+.1f}%, "
                    f"VIX {vix:.1f} elevated — structural defense."
                ),
                factors={"momentum_20d": round(mom_20d, 4), "vix": vix},
            )

        return self._abstain(ctx, "transition zone — no structural edge")

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


talon = Talon()



================================================
