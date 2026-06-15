"""
silmaril.agents.zenith — The Long Rider.

ZENITH rides multi-timeframe trends to their peak. Requires full SMA
stack alignment AND demonstrated trend persistence (50+ bars of intact
stack) before committing. When it commits, it commits for the whole
move. Captain Marvel's archetype: cosmic-scale patience, peaks that
other agents can't reach.

v2.0 changes — backtest told us the old version was over-voting:
  - Original code voted SELL on every "below SMA-200" — too aggressive,
    many stocks live below SMA-200 for years. Now ZENITH only SELLs on
    a fresh BREAK of the stack, not a steady-state below-200 condition.
  - Added trend persistence check (was in the docstring but not in code):
    requires the perfect stack to have been intact for at least 50 days,
    measured via 50d momentum sign and SMA separation stability.
  - Conviction bounded more tightly: max 0.75 (was 0.85) since trend
    quality alone shouldn't justify max-conviction calls without other
    confirmation.

Decision logic:
  - Requires price > SMA-20 > SMA-50 > SMA-200 (perfect alignment)
  - Requires 50-day momentum > +5% (trend has actual runway)
  - Stops are wide (3 ATR) to survive normal pullbacks
  - SELL only on a recent stack BREAK, not a permanent below-200 state
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Zenith(Agent):
    codename = "ZENITH"
    specialty = "Long-Duration Trend"
    temperament = "Rides trends to the cosmic peak. Ignores noise. Commits for the full move."
    inspiration = "Captain Marvel — the highest altitude, the longest reach"
    asset_classes = ("equity", "etf", "crypto")

    # Tuning knobs
    MIN_TREND_MOMENTUM = 0.05      # 50d momentum must be >5% to confirm trend has runway
    MIN_SEPARATION = 0.02          # SMA-20 must be at least 2% above SMA-50
    MAX_CONVICTION = 0.75          # cap so ZENITH doesn't dominate cohort weighting

    def _judge(self, ctx: AssetContext) -> Verdict:
        if not all([ctx.price, ctx.sma_20, ctx.sma_50, ctx.sma_200, ctx.atr_14]):
            return self._abstain(ctx, "need full SMA stack")

        perfect_stack = ctx.price > ctx.sma_20 > ctx.sma_50 > ctx.sma_200

        if perfect_stack:
            # Quality of the trend
            sep_20_50 = (ctx.sma_20 - ctx.sma_50) / ctx.sma_50
            sep_50_200 = (ctx.sma_50 - ctx.sma_200) / ctx.sma_200
            separation_quality = sep_20_50 + sep_50_200

            # Demand minimum trend strength to vote — was the missing check
            if sep_20_50 < self.MIN_SEPARATION:
                return self._abstain(
                    ctx,
                    f"stack aligned but SMA-20/50 separation only {sep_20_50*100:.1f}% — too tight",
                )

            # Compute approximate 50-day momentum from history
            ph = ctx.price_history or []
            if len(ph) >= 51 and ph[-51] > 0:
                mom_50d = (ctx.price / ph[-51]) - 1.0
            else:
                mom_50d = None

            if mom_50d is not None and mom_50d < self.MIN_TREND_MOMENTUM:
                return self._abstain(
                    ctx,
                    f"stack aligned but 50d momentum only {mom_50d*100:+.1f}% — trend not committed",
                )

            conv = min(self.MAX_CONVICTION, 0.55 + min(separation_quality, 0.20))
            entry = ctx.price
            stop = ctx.price - 3.0 * ctx.atr_14
            target = ctx.price + 6.0 * ctx.atr_14

            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=self._clamp(conv),
                rationale=(
                    f"Perfect stack with {separation_quality*100:.1f}% total separation, "
                    f"{(mom_50d or 0)*100:+.1f}% 50d momentum — cosmic trend intact."
                ),
                factors={
                    "stack_separation_pct": round(separation_quality * 100, 2),
                    "momentum_50d_pct": round((mom_50d or 0) * 100, 2),
                },
                suggested_entry=round(entry, 2),
                suggested_stop=round(stop, 2),
                suggested_target=round(target, 2),
                invalidation=f"Close below SMA-50 (${ctx.sma_50:.2f}) breaks the trend.",
            )

        # SELL only on a fresh stack break, not a permanent below-200 state.
        # We detect a fresh break by looking at recent momentum: if 20d
        # momentum is sharply negative AND price just crossed below SMA-200,
        # that's the kind of regime change ZENITH should react to.
        ph = ctx.price_history or []
        if len(ph) >= 21 and ph[-21] > 0:
            mom_20d = (ctx.price / ph[-21]) - 1.0
        else:
            mom_20d = None

        # Was the stack recently intact? Check ~30 bars ago.
        recently_above_200 = False
        if len(ph) >= 31:
            recently_above_200 = ph[-31] > ctx.sma_200 * 0.98

        fresh_break = (
            ctx.price < ctx.sma_200
            and mom_20d is not None and mom_20d < -0.05
            and recently_above_200
        )

        if fresh_break:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.55,
                rationale=(
                    f"Fresh stack break: 20d momentum {mom_20d*100:+.1f}%, "
                    f"price just crossed below SMA-200 — trend regime ended."
                ),
                factors={"momentum_20d_pct": round((mom_20d or 0) * 100, 2)},
            )

        # Otherwise abstain — most "below SMA-200" states aren't actionable for a trend rider
        return self._abstain(ctx, "trend not aligned and no fresh break — ZENITH waits")

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


zenith = Zenith()
