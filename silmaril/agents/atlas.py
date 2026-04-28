"""ATLAS — macro strategist.

Drop-in adapter that matches the SILMARIL agent interface:
  - module-level lowercase instance `atlas`
  - methods: applies_to(ctx) -> bool, evaluate(ctx) -> Verdict
  - uses .base.Verdict / .base.Signal

Premise: when broad-market correlations spike (panic → everything moves
together), reduce equity exposure / lean defensive. When VIX is calm,
allow risk-on lean. ATLAS only votes on broad ETFs; abstains otherwise.
"""
from __future__ import annotations

from .base import Agent, AssetContext, Verdict, Signal


ATLAS_UNIVERSE = {
    "SPY", "QQQ", "IWM", "DIA", "VTI", "EFA", "EEM",
    "TLT", "IEF", "SHY", "HYG", "LQD",
    "GLD", "SLV", "USO", "DBC",
    "XLF", "XLK", "XLV", "XLY", "XLP", "XLE", "XLI", "XLU", "XLB", "XLRE",
}

DEFENSIVE = {"TLT", "IEF", "GLD", "SHY", "XLU", "XLP"}
EQUITY_BROAD = {"SPY", "QQQ", "IWM", "DIA", "VTI"}


class _AtlasAgent(Agent):
    codename = "ATLAS"
    bio = (
        "ATLAS reads the whole sky, not one star. When broad correlations "
        "spike — VIX > 30 or stocks/bonds/commodities all moving together "
        "— the regime has changed and risk should come down. When VIX is "
        "calm and breadth is healthy, ATLAS leans constructive on indexes."
    )

    def applies_to(self, ctx: AssetContext) -> bool:
        return ctx.ticker in ATLAS_UNIVERSE

    def evaluate(self, ctx: AssetContext) -> Verdict:
        vix = getattr(ctx, "vix", None)

        if vix is not None:
            if vix >= 30:
                if ctx.ticker in DEFENSIVE:
                    return Verdict(
                        agent=self.codename,
                        signal=Signal.BUY,
                        conviction=0.60,
                        rationale=f"VIX {vix:.0f} → flight to defensives",
                    )
                if ctx.ticker in EQUITY_BROAD:
                    return Verdict(
                        agent=self.codename,
                        signal=Signal.SELL,
                        conviction=0.55,
                        rationale=f"VIX {vix:.0f} → reduce equity exposure",
                    )
            if vix < 14 and ctx.ticker in EQUITY_BROAD:
                return Verdict(
                    agent=self.codename,
                    signal=Signal.BUY,
                    conviction=0.50,
                    rationale=f"VIX {vix:.1f} → calm regime, lean long broad equity",
                )

        # Trend confirmation fallback for the indexes
        if ctx.ticker in EQUITY_BROAD:
            sma50 = getattr(ctx, "sma_50", None)
            sma200 = getattr(ctx, "sma_200", None)
            if sma50 and sma200 and ctx.price:
                if ctx.price > sma50 > sma200:
                    return Verdict(
                        agent=self.codename,
                        signal=Signal.BUY,
                        conviction=0.45,
                        rationale="price > 50d > 200d → constructive macro stance",
                    )
                if ctx.price < sma50 < sma200:
                    return Verdict(
                        agent=self.codename,
                        signal=Signal.SELL,
                        conviction=0.45,
                        rationale="price < 50d < 200d → defensive macro stance",
                    )

        return Verdict(
            agent=self.codename,
            signal=Signal.HOLD,
            conviction=0.0,
            rationale="macro indicators uncommitted",
        )


atlas = _AtlasAgent()
