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
