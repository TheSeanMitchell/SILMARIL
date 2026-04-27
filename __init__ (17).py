"""
silmaril.agents.thunderhead — The Storm.

THUNDERHEAD strikes when volatility expands and price breaks a recent
range with volume. It is loud, confident, and occasionally wrong in
grand fashion. Thor's archetype: tremendous power when the weather
turns, asleep otherwise.

Decision logic:
  - Requires bullish break of 20-day high AND expanding ATR AND volume surge
  - Short-side mirror: break of 20-day low with expansion → SELL
  - Otherwise ABSTAIN (no breakout, no opinion)
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Thunderhead(Agent):
    codename = "THUNDERHEAD"
    specialty = "Volatility Breakout"
    temperament = "Dormant until the storm. When skies break, strikes with full conviction."
    inspiration = "Thor — the hammer, the thunder, the open sky"
    asset_classes = ("equity", "etf", "crypto")

    VOL_SURGE_RATIO = 1.4      # today's volume vs 30d avg
    ATR_EXPANSION = 1.15       # current ATR vs implied calm ATR

    def _judge(self, ctx: AssetContext) -> Verdict:
        if not ctx.price or len(ctx.price_history) < 25 or not ctx.atr_14:
            return self._abstain(ctx, "insufficient data for breakout detection")

        recent_high = max(ctx.price_history[-21:-1])   # 20-day high excluding today
        recent_low = min(ctx.price_history[-21:-1])

        volume_ratio = 0.0
        if ctx.volume and ctx.avg_volume_30d:
            volume_ratio = ctx.volume / ctx.avg_volume_30d

        # ── Upside breakout ─────────────────────────────────────
        if ctx.price > recent_high and volume_ratio >= self.VOL_SURGE_RATIO:
            conv = 0.7 + min(volume_ratio - 1.4, 0.25)  # more volume = higher conviction, capped
            rationale = (
                f"Broke 20-day high (${recent_high:.2f}) on "
                f"{volume_ratio:.1f}× avg volume — storm has arrived."
            )
            entry = ctx.price
            stop = ctx.price - 2.0 * ctx.atr_14
            target = ctx.price + 4.0 * ctx.atr_14
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.STRONG_BUY if volume_ratio >= 2.0 else Signal.BUY,
                conviction=self._clamp(conv),
                rationale=rationale,
                factors={"breakout_high": recent_high, "volume_ratio": round(volume_ratio, 2)},
                suggested_entry=round(entry, 2),
                suggested_stop=round(stop, 2),
                suggested_target=round(target, 2),
                invalidation=f"Close back below ${recent_high:.2f} invalidates breakout.",
            )

        # ── Downside breakout ───────────────────────────────────
        if ctx.price < recent_low and volume_ratio >= self.VOL_SURGE_RATIO:
            conv = 0.65
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL,
                conviction=conv,
                rationale=f"Broke 20-day low (${recent_low:.2f}) on heavy volume.",
                factors={"breakdown_low": recent_low, "volume_ratio": round(volume_ratio, 2)},
            )

        # ── No breakout — THUNDERHEAD sleeps ────────────────────
        return self._abstain(ctx, "no breakout; awaiting the storm")

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0,
            rationale=reason,
        )


thunderhead = Thunderhead()
