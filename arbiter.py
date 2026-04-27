"""
silmaril.agents.jade — The Rage-Buyer.

JADE waits through calm markets with no opinion, then rage-buys panic.
Its signature setup is a deeply oversold RSI near major support, when
everyone else is selling. Hulk's archetype: quiet until pushed, then
unstoppable.

Decision logic:
  - Only takes BUY signals. Never sells, never shorts.
  - Requires RSI < 30 AND price within 5% of SMA-200 (support).
  - Bonus conviction if sentiment is extremely negative (capitulation).
  - Otherwise ABSTAIN.
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Jade(Agent):
    codename = "JADE"
    specialty = "Oversold Mean Reversion"
    temperament = "Silent in calm markets. When panic peaks, rage-buys the capitulation."
    inspiration = "Hulk — the greener he gets, the stronger he becomes"
    asset_classes = ("equity", "etf")

    OVERSOLD = 30.0
    DEEPLY_OVERSOLD = 22.0
    NEAR_SUPPORT = 0.05          # within 5% of SMA-200

    def _judge(self, ctx: AssetContext) -> Verdict:
        if ctx.rsi_14 is None or not ctx.price or not ctx.sma_200 or not ctx.atr_14:
            return self._abstain(ctx, "awaiting oversold conditions")

        if ctx.rsi_14 > self.OVERSOLD:
            return self._abstain(ctx, f"RSI {ctx.rsi_14:.0f} — not yet oversold")

        dist_from_200 = abs(ctx.price - ctx.sma_200) / ctx.sma_200
        if dist_from_200 > self.NEAR_SUPPORT:
            return self._abstain(ctx, "oversold but too far from major support")

        # Deep oversold + negative sentiment = capitulation = STRONG setup
        deeply_oversold = ctx.rsi_14 < self.DEEPLY_OVERSOLD
        capitulating = (ctx.sentiment_score or 0) < -0.3 and ctx.article_count >= 3
        signal = Signal.STRONG_BUY if (deeply_oversold and capitulating) else Signal.BUY

        conv = 0.55
        if deeply_oversold: conv += 0.1
        if capitulating:    conv += 0.1

        rationale = (
            f"RSI {ctx.rsi_14:.0f} at major support (SMA-200 ${ctx.sma_200:.2f})"
            + (" with heavy negative sentiment — capitulation." if capitulating else " — contrarian entry.")
        )
        entry = ctx.price
        stop = ctx.price - 1.5 * ctx.atr_14
        target = ctx.price + 3.5 * ctx.atr_14

        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=signal, conviction=self._clamp(conv),
            rationale=rationale,
            factors={"rsi": round(ctx.rsi_14, 1), "dist_sma200_pct": round(dist_from_200 * 100, 2)},
            suggested_entry=round(entry, 2),
            suggested_stop=round(stop, 2),
            suggested_target=round(target, 2),
            invalidation=f"Close below ${stop:.2f} breaks the thesis; capitulation was not the bottom.",
        )

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


jade = Jade()
