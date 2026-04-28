"""
silmaril.agents.shepherd — The Bond Yield Watcher.

SHEPHERD watches the 10-year Treasury yield and rotates between bonds
and rate-sensitive sectors. When 10Y rises fast, rate-sensitives squeeze
and duration sells off. When yields ease, the same sectors catch a bid.

v2.0 changes — backtest revealed 46.6% win rate. The original 25bps
trigger was too loose (fires on roughly 1/3 of all 5-day windows).
Tightened to 35bps. Added an RSI mean-revert path on bond ETFs because
they tend to mean-revert intraweek.
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

    YIELD_SPIKE_BPS = 35      # was 25, too loose
    EXTREME_VIX = 30
    BOND_OVERSOLD_RSI = 30
    BOND_OVERBOUGHT_RSI = 72

    def applies_to(self, ctx: AssetContext) -> bool:
        return ctx.ticker in SHEPHERD_UNIVERSE

    def _judge(self, ctx: AssetContext) -> Verdict:
        tnx_5d = getattr(ctx, "tnx_change_5d_bps", None)
        regime = ctx.market_regime
        vix = ctx.vix
        rsi = ctx.rsi_14 or 50

        # ── Yield-driven trades (highest priority) ──
        if tnx_5d is not None:
            if tnx_5d >= self.YIELD_SPIKE_BPS and ctx.ticker in BONDS:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.60,
                    rationale=f"10Y +{tnx_5d:.0f}bp/5d → bonds oversold, mean-revert.",
                    factors={"tnx_change_5d_bps": tnx_5d},
                )
            if tnx_5d >= self.YIELD_SPIKE_BPS and ctx.ticker in RATE_SENSITIVE:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.SELL, conviction=0.55,
                    rationale=f"10Y +{tnx_5d:.0f}bp/5d → rate-sensitives squeezed.",
                    factors={"tnx_change_5d_bps": tnx_5d},
                )
            if tnx_5d <= -self.YIELD_SPIKE_BPS and ctx.ticker in RATE_SENSITIVE:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.55,
                    rationale=f"10Y {tnx_5d:.0f}bp/5d → rate-sensitive tailwind.",
                    factors={"tnx_change_5d_bps": tnx_5d},
                )

        # ── Mean-revert on bond ETFs by RSI ──
        if ctx.ticker in BONDS:
            if rsi < self.BOND_OVERSOLD_RSI:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.55,
                    rationale=f"Bond {ctx.ticker} oversold (RSI {rsi:.0f}) — mean-revert.",
                    factors={"rsi": rsi, "mode": "mean_revert"},
                )
            if rsi > self.BOND_OVERBOUGHT_RSI:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.SELL, conviction=0.50,
                    rationale=f"Bond {ctx.ticker} overbought (RSI {rsi:.0f}) — mean-revert.",
                    factors={"rsi": rsi, "mode": "mean_revert"},
                )

        # ── Regime fallback ──
        if regime == "RISK_OFF" and ctx.ticker in BONDS:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.50,
                rationale="Risk-off → duration tailwind.",
                factors={"regime": regime},
            )
        if vix and vix >= self.EXTREME_VIX and ctx.ticker in BONDS:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.50,
                rationale=f"VIX {vix:.0f} → flight-to-quality bid.",
                factors={"vix": vix},
            )

        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.HOLD, conviction=0.0,
            rationale="rate signal not decisive",
        )


shepherd = Shepherd()
