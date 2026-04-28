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
