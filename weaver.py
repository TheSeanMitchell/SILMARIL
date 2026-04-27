"""
silmaril.agents.talon — The Overhead View.

TALON only evaluates the broad indices: SPY, QQQ, IWM, DIA, VTI. Its
lens is market structure — regime, breadth, breakout vs. breakdown at
the index level. It doesn't care about individual names; it cares about
the shape of the whole market.

Falcon's archetype: aerial perspective, the overhead view.

Decision logic:
  - Index above SMA-200 + rising SMA-50 = RISK_ON → BUY index
  - Index below SMA-200 = broken trend → SELL index
  - VIX > 25 + mixed index position → HOLD (too choppy)
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


INDEX_TICKERS = {"SPY", "QQQ", "DIA", "IWM", "VTI"}


class Talon(Agent):
    codename = "TALON"
    specialty = "Market Structure"
    temperament = "Aerial view. Evaluates only the indices. Market shape, not individual names."
    inspiration = "Falcon — the overhead view, the aerial perspective"
    asset_classes = ("etf",)

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker.upper() in INDEX_TICKERS

    def _judge(self, ctx: AssetContext) -> Verdict:
        if not ctx.price or not ctx.sma_50 or not ctx.sma_200:
            return self._hold(ctx, "insufficient index structure data")

        above_200 = ctx.price > ctx.sma_200
        above_50 = ctx.price > ctx.sma_50
        stack_up = ctx.sma_50 > ctx.sma_200

        # Elevated VIX caution
        if ctx.vix and ctx.vix > 25:
            if not above_200:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.SELL, conviction=0.65,
                    rationale=f"Index below SMA-200 with VIX {ctx.vix:.1f} — structurally defensive.",
                    factors={"vix": ctx.vix, "above_sma200": False},
                )
            return self._hold(ctx, f"VIX {ctx.vix:.1f} elevated — awaiting resolution")

        if above_200 and above_50 and stack_up:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.6,
                rationale="Index above both SMAs with rising 50-day — structurally risk-on.",
                factors={"above_sma200": True, "above_sma50": True},
                suggested_entry=ctx.price,
                suggested_stop=round(ctx.sma_50, 2) if ctx.sma_50 else None,
                suggested_target=round(ctx.price * 1.06, 2),
                invalidation="Close below SMA-50 invalidates the structure thesis.",
            )

        if not above_200:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.55,
                rationale="Index below SMA-200 — structural downtrend.",
                factors={"above_sma200": False},
            )

        return self._hold(ctx, "index in transition zone — no structural edge")

    def _hold(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.HOLD, conviction=0.4, rationale=reason,
        )


talon = Talon()
