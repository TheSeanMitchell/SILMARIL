"""SHEPHERD — bond-yield watcher, votes on bonds and rate-sensitive
sectors only. Listens for signals via VIX/regime/optional 10Y series.
"""
from __future__ import annotations

from .base import Agent, AssetContext, Verdict, Signal


BONDS = {"TLT", "IEF", "SHY", "AGG", "BND", "HYG", "LQD", "MUB", "TIP", "VTEB"}
RATE_SENSITIVE = {"XLU", "IYR", "VNQ", "XLP", "XLRE"}
SHEPHERD_UNIVERSE = BONDS | RATE_SENSITIVE


class _ShepherdAgent(Agent):
    codename = "SHEPHERD"
    bio = (
        "SHEPHERD watches the long end. When 10Y rises fast, "
        "rate-sensitives squeeze and duration eventually catches a bid. "
        "When yields ease, the opposite. Only votes on bonds and "
        "rate-sensitive equity sectors."
    )

    def applies_to(self, ctx: AssetContext) -> bool:
        return ctx.ticker in SHEPHERD_UNIVERSE

    def evaluate(self, ctx: AssetContext) -> Verdict:
        # Optional explicit signal: 5-day change in 10Y yield in basis points
        tnx_5d_bps = getattr(ctx, "tnx_change_5d_bps", None)
        regime = getattr(ctx, "market_regime", None)
        vix = getattr(ctx, "vix", None)

        if tnx_5d_bps is not None:
            if tnx_5d_bps >= 25 and ctx.ticker in BONDS:
                return Verdict(
                    agent=self.codename, signal=Signal.BUY, conviction=0.55,
                    rationale=f"10Y +{tnx_5d_bps:.0f}bp in 5d → bonds oversold, mean revert",
                )
            if tnx_5d_bps >= 25 and ctx.ticker in RATE_SENSITIVE:
                return Verdict(
                    agent=self.codename, signal=Signal.SELL, conviction=0.55,
                    rationale=f"10Y +{tnx_5d_bps:.0f}bp in 5d → rate-sensitives squeezed",
                )
            if tnx_5d_bps <= -25 and ctx.ticker in RATE_SENSITIVE:
                return Verdict(
                    agent=self.codename, signal=Signal.BUY, conviction=0.55,
                    rationale=f"10Y {tnx_5d_bps:.0f}bp in 5d → tailwind for rate-sensitives",
                )

        # Regime fallback
        if regime == "BEAR" and ctx.ticker in BONDS:
            return Verdict(
                agent=self.codename, signal=Signal.BUY, conviction=0.45,
                rationale="bear regime → duration tailwind",
            )
        if vix and vix > 28 and ctx.ticker in BONDS:
            return Verdict(
                agent=self.codename, signal=Signal.BUY, conviction=0.45,
                rationale=f"VIX {vix:.0f} → flight-to-quality bid for duration",
            )

        return Verdict(
            agent=self.codename, signal=Signal.HOLD, conviction=0.0,
            rationale="rate signal not decisive today",
        )


shepherd = _ShepherdAgent()
