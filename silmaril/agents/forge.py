"""
silmaril.agents.forge — The Forge.

FORGE is the offensive innovator of the team. Where AEGIS defends,
FORGE builds. Its domain is technology — the sector where disruption,
iteration, and scale compound fastest.

Trading philosophy (Iron Man archetype):
  - Calculated risk, not reckless risk
  - Biases toward quality technology names in momentum
  - Values earnings beats, guidance raises, product launches
  - Comfortable with higher volatility than AEGIS tolerates

Decision logic:
  1. Applies only to tech-sector equities and the tech-heavy ETFs (QQQ, XLK, SMH, SOXX).
  2. Strong uptrend stack + positive sentiment + earnings beat → STRONG_BUY
  3. Clean uptrend + positive sentiment → BUY
  4. Downtrend or RSI < 40 in tech → SELL (FORGE does not bottom-fish; that's JADE's job)
  5. Otherwise → HOLD
"""

from __future__ import annotations

from typing import Optional

from .base import Agent, AssetContext, Signal, Verdict


# Tech-sector anchor tickers FORGE evaluates. Everything else → ABSTAIN.
TECH_ANCHORS = {
    # Mega-cap tech
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    "ORCL", "CRM", "ADBE", "AVGO", "AMD", "INTC", "CSCO", "IBM",
    # Tech ETFs
    "QQQ", "XLK", "SMH", "SOXX", "VGT", "IGV", "ARKK", "ARKW",
    # Growth-tech secondary
    "NFLX", "DIS", "PYPL", "SQ", "SHOP", "SNOW", "PLTR", "NOW",
    "PANW", "ZS", "CRWD", "DDOG", "NET", "MDB", "TEAM", "WDAY",
    "ASML", "TSM", "QCOM", "MU", "AMAT", "LRCX", "KLAC",
}


class Forge(Agent):
    codename = "FORGE"
    specialty = "Tech-Sector Momentum"
    temperament = (
        "Builder's confidence. Believes technology compounds faster than "
        "other sectors and bets accordingly — but only on clean setups with "
        "measurable catalysts."
    )
    inspiration = "Iron Man — the suit is built, piece by piece"
    asset_classes = ("equity", "etf")

    # Thresholds
    STRONG_BUY_SENTIMENT = 0.4
    BUY_SENTIMENT = 0.15
    OVERSOLD_RSI = 40.0
    TREND_STRENGTH_MIN = 0.03     # price must be 3%+ above 50-day SMA to call it trend

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker.upper() in TECH_ANCHORS

    def _judge(self, ctx: AssetContext) -> Verdict:
        reasons: list[str] = []
        factors: dict = {}

        # ── Guard: need core data ────────────────────────────────
        if not all([ctx.price, ctx.sma_20, ctx.sma_50]):
            return self._hold_for_data(ctx)

        # ── Trend stack ──────────────────────────────────────────
        price_above_20 = ctx.price > ctx.sma_20
        price_above_50 = ctx.price > ctx.sma_50
        stack_aligned = ctx.sma_20 > ctx.sma_50
        trend_strength = self._pct_above(ctx.price, ctx.sma_50)
        factors["trend_strength_vs_sma50"] = round(trend_strength, 4)

        clean_uptrend = (
            price_above_20
            and price_above_50
            and stack_aligned
            and trend_strength >= self.TREND_STRENGTH_MIN
        )

        # ── Sentiment heat ───────────────────────────────────────
        sentiment = ctx.sentiment_score or 0.0
        factors["sentiment_score"] = round(sentiment, 3)
        factors["article_count"] = ctx.article_count

        # ── Earnings catalyst ────────────────────────────────────
        earnings_soon = (
            ctx.days_to_earnings is not None and 0 <= ctx.days_to_earnings <= 7
        )
        if earnings_soon:
            factors["earnings_window"] = ctx.days_to_earnings
            reasons.append(f"earnings in {ctx.days_to_earnings} days")

        # ── Decision tree ────────────────────────────────────────

        # STRONG_BUY: clean uptrend + strong sentiment + decent volume
        if clean_uptrend and sentiment >= self.STRONG_BUY_SENTIMENT and ctx.article_count >= 3:
            reasons.append(
                f"clean uptrend (+{trend_strength*100:.1f}% vs SMA50), "
                f"strong sentiment {sentiment:+.2f}, {ctx.article_count} articles"
            )
            return self._build_verdict(
                ctx, Signal.STRONG_BUY, conviction=0.78,
                reasons=reasons, factors=factors,
                atr_mult_stop=2.0, atr_mult_target=4.0,
            )

        # BUY: clean uptrend + positive sentiment
        if clean_uptrend and sentiment >= self.BUY_SENTIMENT:
            reasons.append(
                f"uptrend intact (+{trend_strength*100:.1f}% vs SMA50), "
                f"sentiment {sentiment:+.2f}"
            )
            return self._build_verdict(
                ctx, Signal.BUY, conviction=0.6,
                reasons=reasons, factors=factors,
                atr_mult_stop=2.0, atr_mult_target=3.5,
            )

        # SELL: downtrend or oversold-and-no-bounce-catalyst
        if (ctx.rsi_14 and ctx.rsi_14 < self.OVERSOLD_RSI) or not price_above_50:
            rsi_val = ctx.rsi_14 or 0
            reasons.append(
                f"tech name in downtrend (below SMA50)" if not price_above_50
                else f"oversold RSI {rsi_val:.0f} without trend support"
            )
            return self._build_verdict(
                ctx, Signal.SELL, conviction=0.55,
                reasons=reasons, factors=factors,
            )

        # HOLD: setup not clean enough
        reasons.append("setup not yet aligned; awaiting clearer trend")
        return self._build_verdict(
            ctx, Signal.HOLD, conviction=0.4,
            reasons=reasons, factors=factors,
        )

    # ─────────────────────────────────────────────────────────────

    def _hold_for_data(self, ctx: AssetContext) -> Verdict:
        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=Signal.HOLD,
            conviction=0.2,
            rationale="Awaiting sufficient price history to form a momentum view.",
            factors={"insufficient_data": True},
        )

    def _build_verdict(
        self,
        ctx: AssetContext,
        signal: Signal,
        conviction: float,
        reasons: list[str],
        factors: dict,
        atr_mult_stop: Optional[float] = None,
        atr_mult_target: Optional[float] = None,
    ) -> Verdict:
        rationale = self._compose(reasons, signal)

        entry = stop = target = None
        invalidation = None
        if signal in (Signal.BUY, Signal.STRONG_BUY) and ctx.price and ctx.atr_14:
            entry = round(ctx.price, 2)
            if atr_mult_stop:
                stop = round(ctx.price - atr_mult_stop * ctx.atr_14, 2)
            if atr_mult_target:
                target = round(ctx.price + atr_mult_target * ctx.atr_14, 2)
            invalidation = (
                f"Close below ${stop:.2f} OR break of SMA50 (${ctx.sma_50:.2f}) "
                f"invalidates the momentum thesis."
            )

        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=signal,
            conviction=self._clamp(conviction),
            rationale=rationale,
            factors=factors,
            suggested_entry=entry,
            suggested_stop=stop,
            suggested_target=target,
            invalidation=invalidation,
        )

    @staticmethod
    def _compose(reasons: list[str], signal: Signal) -> str:
        stance = {
            Signal.STRONG_BUY: "High-conviction build: ",
            Signal.BUY: "Constructive: ",
            Signal.SELL: "Step away: ",
            Signal.HOLD: "Standing by: ",
        }.get(signal, "")
        return f"{stance}{'; '.join(reasons)}."


forge = Forge()
