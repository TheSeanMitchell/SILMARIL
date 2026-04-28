"""
silmaril.agents.shepherd — The Bond Yield Watcher.

SHEPHERD watches the 10-year Treasury yield. When 10Y rises fast,
rate-sensitive sectors (utilities, REITs, staples) get squeezed.
When yields ease, the same sectors catch a bid. SHEPHERD only votes
on bonds and rate-sensitive equity sectors — never broad equity.

Optional upstream field:
  - tnx_change_5d_bps: float, change in 10Y yield over last 5 days (bps)

Falls back to VIX/regime signal if explicit yield data isn't wired.
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


BONDS = {"TLT", "IEF", "SHY", "AGG", "BND", "HYG", "LQD", "MUB", "TIP", "VTEB"}
RATE_SENSITIVE = {"XLU", "IYR", "VNQ", "XLP", "XLRE"}
SHEPHERD_UNIVERSE = BONDS | RATE_SENSITIVE


class Shepherd(Agent):
    codename = "SHEPHERD"
    specialty = "Bond & Rate-Sensitive Sector Specialist"
    temperament = (
        "Methodical, watches the long end. When the 10Y moves fast, "
        "the rate-sensitive flock scatters — SHEPHERD calls them home "
        "before the move completes."
    )
    inspiration = "The shepherd — moves the flock before the storm hits"
    asset_classes = ("etf",)

    def applies_to(self, ctx: AssetContext) -> bool:
        return ctx.ticker in SHEPHERD_UNIVERSE

    def _judge(self, ctx: AssetContext) -> Verdict:
        tnx_5d = getattr(ctx, "tnx_change_5d_bps", None)
        regime = ctx.market_regime
        vix = ctx.vix

        # Explicit yield change signal
        if tnx_5d is not None:
            if tnx_5d >= 25 and ctx.ticker in BONDS:
                return Verdict(
                    agent=self.codename,
                    ticker=ctx.ticker,
                    signal=Signal.BUY,
                    conviction=0.55,
                    rationale=f"10Y +{tnx_5d:.0f}bp/5d → bonds oversold, mean revert",
                    factors={"tnx_change_5d_bps": tnx_5d},
                )
            if tnx_5d >= 25 and ctx.ticker in RATE_SENSITIVE:
                return Verdict(
                    agent=self.codename,
                    ticker=ctx.ticker,
                    signal=Signal.SELL,
                    conviction=0.55,
                    rationale=f"10Y +{tnx_5d:.0f}bp/5d → rate-sensitives squeezed",
                    factors={"tnx_change_5d_bps": tnx_5d},
                )
            if tnx_5d <= -25 and ctx.ticker in RATE_SENSITIVE:
                return Verdict(
                    agent=self.codename,
                    ticker=ctx.ticker,
                    signal=Signal.BUY,
                    conviction=0.55,
                    rationale=f"10Y {tnx_5d:.0f}bp/5d → tailwind for rate-sensitives",
                    factors={"tnx_change_5d_bps": tnx_5d},
                )

        # Regime fallback for bonds
        if regime == "RISK_OFF" and ctx.ticker in BONDS:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.BUY,
                conviction=0.45,
                rationale="risk-off regime → duration tailwind",
                factors={"regime": regime},
            )

        # VIX panic flight-to-quality
        if vix and vix >= 28 and ctx.ticker in BONDS:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.BUY,
                conviction=0.45,
                rationale=f"VIX {vix:.0f} → flight-to-quality bid for duration",
                factors={"vix": vix},
            )

        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=Signal.HOLD,
            conviction=0.0,
            rationale="rate signal not decisive",
        )


shepherd = Shepherd()
