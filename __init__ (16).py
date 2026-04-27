"""
silmaril.agents.weaver — The Micro Scalper.

WEAVER hunts short-term moves: RSI swings from overbought to oversold
and back, quick bounces off SMA-20, intraday-style opportunities.
Takes smaller moves with faster exits than the trend agents. Spider-
Man's archetype: quick, nimble, many small wins.

Decision logic:
  - RSI reversal from extreme: < 35 turning up → BUY; > 65 turning down → SELL
  - Price pulling back to SMA-20 in an uptrend → BUY
  - Tight 1.5 ATR stops, 2.5 ATR targets (1.67:1 R:R)
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Weaver(Agent):
    codename = "WEAVER"
    specialty = "Micro Scalper"
    temperament = "Quick, nimble. Takes many small wins. Not every web catches a fly."
    inspiration = "Spider-Man — speed and small wins compound"
    asset_classes = ("equity", "etf")

    RSI_OVERSOLD = 35.0
    RSI_OVERBOUGHT = 65.0
    PULLBACK_PCT = 0.015   # price within 1.5% of SMA-20

    def _judge(self, ctx: AssetContext) -> Verdict:
        if not ctx.price or not ctx.sma_20 or not ctx.atr_14 or ctx.rsi_14 is None:
            return self._abstain(ctx, "insufficient data for scalp")

        # ── RSI reversal from extreme oversold ──────────────────
        if ctx.rsi_14 < self.RSI_OVERSOLD and ctx.sma_50 and ctx.price > ctx.sma_50:
            return self._long_scalp(ctx, f"RSI {ctx.rsi_14:.0f} bouncing in larger uptrend")

        # ── Pullback to SMA-20 in uptrend ───────────────────────
        if ctx.sma_50 and ctx.sma_20 > ctx.sma_50:
            dist = abs(ctx.price - ctx.sma_20) / ctx.sma_20
            if dist < self.PULLBACK_PCT and ctx.price >= ctx.sma_20 * 0.99:
                return self._long_scalp(ctx, f"Pullback to SMA-20 (${ctx.sma_20:.2f}) in uptrend")

        # ── RSI overbought reversal ─────────────────────────────
        if ctx.rsi_14 > self.RSI_OVERBOUGHT and ctx.sma_50 and ctx.price < ctx.sma_50:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.5,
                rationale=f"RSI {ctx.rsi_14:.0f} extreme in larger downtrend — quick short.",
                factors={"rsi": round(ctx.rsi_14, 1)},
            )

        return self._abstain(ctx, "no quick setup today")

    def _long_scalp(self, ctx: AssetContext, reason: str) -> Verdict:
        entry = ctx.price
        stop = ctx.price - 1.5 * ctx.atr_14
        target = ctx.price + 2.5 * ctx.atr_14
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.BUY, conviction=0.55,
            rationale=reason,
            factors={"rsi": round(ctx.rsi_14 or 0, 1)},
            suggested_entry=round(entry, 2),
            suggested_stop=round(stop, 2),
            suggested_target=round(target, 2),
            invalidation=f"Tight stop: ${stop:.2f}. Bounce fails, exit immediately.",
        )

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


weaver = Weaver()
