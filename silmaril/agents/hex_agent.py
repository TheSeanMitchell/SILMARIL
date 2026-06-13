"""
silmaril.agents.hex — The Probabilist.

HEX looks for statistical extremes where mean reversion is probable.
Its setups are quiet but mathematically grounded: multi-sigma moves
from recent average, gap fills, historical base-rate edges.

Scarlet Witch's archetype: bends probability, reads the odds.

Decision logic:
  - 2+ sigma move below 20-day mean → BUY (mean reversion)
  - 2+ sigma move above 20-day mean (on waning volume) → SELL
  - Measured conviction scales with how extreme the deviation is
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Hex(Agent):
    codename = "HEX"
    specialty = "Probabilistic Edge"
    temperament = "Reads the odds. Trades extremes when the probability bends its way."
    inspiration = "Scarlet Witch — probability-bending, hex of fortune"
    asset_classes = ("equity", "etf", "crypto")

    SIGMA_THRESHOLD = 2.0

    def _judge(self, ctx: AssetContext) -> Verdict:
        if not ctx.price or len(ctx.price_history) < 21 or not ctx.atr_14:
            return self._abstain(ctx, "insufficient history for statistical measure")

        window = ctx.price_history[-20:]
        mean = sum(window) / len(window)
        variance = sum((x - mean) ** 2 for x in window) / len(window)
        stdev = variance ** 0.5
        if stdev == 0:
            return self._abstain(ctx, "zero volatility — no edge")

        z = (ctx.price - mean) / stdev

        # ── Deeply below mean → reversion buy ───────────────────
        if z <= -self.SIGMA_THRESHOLD:
            conv = self._clamp(0.5 + (abs(z) - self.SIGMA_THRESHOLD) * 0.1)
            entry = ctx.price
            stop = ctx.price - 1.5 * ctx.atr_14
            target = mean
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=conv,
                rationale=f"Price {z:.2f}σ below 20-day mean — reversion probable.",
                factors={"z_score": round(z, 2), "mean_20d": round(mean, 2)},
                suggested_entry=round(entry, 2),
                suggested_stop=round(stop, 2),
                suggested_target=round(target, 2),
                invalidation=f"Another 1σ lower (${mean - 3*stdev:.2f}) would invalidate mean-reversion setup.",
            )

        # ── Deeply above mean → reversion sell ──────────────────
        if z >= self.SIGMA_THRESHOLD:
            conv = self._clamp(0.45 + (z - self.SIGMA_THRESHOLD) * 0.1)
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=conv,
                rationale=f"Price {z:.2f}σ above 20-day mean — reversion probable.",
                factors={"z_score": round(z, 2), "mean_20d": round(mean, 2)},
            )

        return self._abstain(ctx, f"z-score {z:+.2f} — within normal range")

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


hex_agent = Hex()   # `hex` is a Python builtin; use a non-colliding module name
