"""
silmaril.agents.zenith — The Long Rider.

ZENITH rides multi-timeframe trends to their peak. Requires full SMA
stack alignment and won't abandon a position on minor pullbacks. When
it commits, it commits for the whole move. Captain Marvel's archetype:
cosmic-scale patience, peaks that other agents can't reach.

Decision logic:
  - Requires price > SMA-20 > SMA-50 > SMA-200 (perfect alignment)
  - Requires trend to have been intact for at least 50 days
  - Stops are wide (3 ATR) to survive normal pullbacks
  - Won't sell on weakness until full-stack breaks
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Zenith(Agent):
    codename = "ZENITH"
    specialty = "Long-Duration Trend"
    temperament = "Rides trends to the cosmic peak. Ignores noise. Commits for the full move."
    inspiration = "Captain Marvel — the highest altitude, the longest reach"
    asset_classes = ("equity", "etf", "crypto")

    def _judge(self, ctx: AssetContext) -> Verdict:
        if not all([ctx.price, ctx.sma_20, ctx.sma_50, ctx.sma_200, ctx.atr_14]):
            return self._abstain(ctx, "need full SMA stack")

        perfect_stack = ctx.price > ctx.sma_20 > ctx.sma_50 > ctx.sma_200
        broken_stack = ctx.price < ctx.sma_200

        if perfect_stack:
            # Measure trend quality by SMA separation
            sep_20_50 = (ctx.sma_20 - ctx.sma_50) / ctx.sma_50
            sep_50_200 = (ctx.sma_50 - ctx.sma_200) / ctx.sma_200
            separation_quality = sep_20_50 + sep_50_200

            conv = 0.6 + min(separation_quality, 0.25)
            entry = ctx.price
            stop = ctx.price - 3.0 * ctx.atr_14   # wide stop to survive pullbacks
            target = ctx.price + 6.0 * ctx.atr_14  # 2:1 R:R over long hold

            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=self._clamp(conv),
                rationale=(
                    f"Perfect stack: price > SMA20 > SMA50 > SMA200, "
                    f"separation {separation_quality*100:.1f}% — cosmic trend intact."
                ),
                factors={"stack_separation_pct": round(separation_quality * 100, 2)},
                suggested_entry=round(entry, 2),
                suggested_stop=round(stop, 2),
                suggested_target=round(target, 2),
                invalidation=f"Close below SMA-200 (${ctx.sma_200:.2f}) — trend broken, exit.",
            )

        if broken_stack:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.55,
                rationale="Price below SMA-200 — long-term trend broken.",
                factors={"below_sma200": True},
            )

        return self._abstain(ctx, "trend not fully aligned — ZENITH waits")

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


zenith = Zenith()
