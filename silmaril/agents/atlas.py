"""
silmaril.agents.atlas — The Macro Strategist.

ATLAS is the regime caller. It only votes on broad-market ETFs and
sector ETFs — never individual stocks. When VIX is high, it leans
defensive. When VIX is calm and trend is up, it leans constructive on
broad equity.

v2.0 changes — backtest revealed ATLAS was 50.4% win rate. The old
"BUY any clean uptrend" logic was firing on every healthy stack, which
includes a lot of mean-reverting tops. Fixed by:
  - Requiring 50d momentum confirmation, not just stack alignment
  - Tightening VIX thresholds (panic at 28, calm at 15)
  - Adding STRONG_BUY when all conditions align
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


ATLAS_UNIVERSE = {
    "SPY", "QQQ", "IWM", "DIA", "VTI", "EFA", "EEM",
    "TLT", "IEF", "SHY", "HYG", "LQD",
    "GLD", "SLV", "USO", "DBC",
    "XLF", "XLK", "XLV", "XLY", "XLP", "XLE", "XLI", "XLU", "XLB", "XLRE",
}

DEFENSIVE_TICKERS = {"TLT", "IEF", "GLD", "SHY", "XLU", "XLP"}
EQUITY_BROAD = {"SPY", "QQQ", "IWM", "DIA", "VTI"}


class Atlas(Agent):
    codename = "ATLAS"
    specialty = "Macro Regime Caller"
    temperament = (
        "Patient, top-down. Reads the whole sky, never one star. Stays "
        "silent on individual stocks; only opines on broad indexes and "
        "sectors."
    )
    inspiration = "Atlas — bears the weight of the entire market"
    asset_classes = ("etf",)

    PANIC_VIX = 28.0
    CALM_VIX = 15.0
    MIN_MOMENTUM = 0.03  # 3% over 50 days

    def applies_to(self, ctx: AssetContext) -> bool:
        return ctx.ticker in ATLAS_UNIVERSE

    def _judge(self, ctx: AssetContext) -> Verdict:
        vix = ctx.vix
        ph = ctx.price_history or []

        mom_50d = None
        if len(ph) >= 51 and ph[-51] > 0:
            mom_50d = (ctx.price / ph[-51]) - 1.0

        # ── Panic regime: defensives buy / equity sell ──
        if vix is not None and vix >= self.PANIC_VIX:
            if ctx.ticker in DEFENSIVE_TICKERS:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.62,
                    rationale=f"VIX {vix:.0f} → flight to defensives",
                    factors={"vix": vix},
                )
            if ctx.ticker in EQUITY_BROAD:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.SELL, conviction=0.55,
                    rationale=f"VIX {vix:.0f} → reduce broad equity",
                    factors={"vix": vix},
                )

        # ── Calm regime + clean uptrend with momentum confirmation ──
        if (
            vix is not None and vix < self.CALM_VIX
            and ctx.ticker in EQUITY_BROAD
            and ctx.price and ctx.sma_50 and ctx.sma_200
            and ctx.price > ctx.sma_50 > ctx.sma_200
            and mom_50d is not None and mom_50d >= self.MIN_MOMENTUM
        ):
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.STRONG_BUY, conviction=0.60,
                rationale=(
                    f"VIX {vix:.1f} calm, clean uptrend, 50d momentum "
                    f"{mom_50d*100:+.1f}% — high-conviction macro long."
                ),
                factors={"vix": vix, "momentum_50d": round(mom_50d, 4)},
            )

        # ── Healthy uptrend without VIX-calm bonus ──
        if (
            ctx.ticker in EQUITY_BROAD
            and ctx.price and ctx.sma_50 and ctx.sma_200
            and ctx.price > ctx.sma_50 > ctx.sma_200
            and mom_50d is not None and mom_50d >= self.MIN_MOMENTUM
            and (vix is None or vix < 20)
        ):
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.50,
                rationale=(
                    f"Constructive macro: stack aligned, 50d momentum "
                    f"{mom_50d*100:+.1f}%, VIX {vix or 'n/a'}."
                ),
                factors={"momentum_50d": round(mom_50d, 4)},
            )

        # ── Fresh trend break ──
        if (
            ctx.ticker in EQUITY_BROAD
            and ctx.price and ctx.sma_50 and ctx.sma_200
            and ctx.price < ctx.sma_50 < ctx.sma_200
            and mom_50d is not None and mom_50d <= -0.05
        ):
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.50,
                rationale=f"Stack broken, 50d momentum {mom_50d*100:+.1f}% — defensive macro.",
                factors={"momentum_50d": round(mom_50d, 4)},
            )

        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0,
            rationale="macro indicators uncommitted",
        )


atlas = Atlas()
