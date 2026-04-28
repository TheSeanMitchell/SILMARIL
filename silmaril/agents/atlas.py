"""
silmaril.agents.atlas — The Macro Strategist.

ATLAS is the regime caller. It only votes on broad-market ETFs and
sector ETFs — never individual stocks. When VIX is high or correlations
are spiking, it leans defensive. When VIX is calm and trend is up, it
leans constructive on broad equity.

Premise: most agents work bottom-up. ATLAS works top-down. It refuses
to opine on a single stock and instead says "the whole sky is angry"
or "the whole sky is calm" — and lets the bottom-up agents act on
their own theses within whatever weather ATLAS sees.

Decision logic:
  1. Skip everything that's not a broad ETF or sector ETF
  2. VIX >= 30 → defensives buy / equity sell
  3. VIX < 14 + clean trend → cautious buy on broad equity
  4. Trend stack (price > 50d > 200d) → constructive bias
  5. Otherwise HOLD
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


# Broad ETFs ATLAS opines on
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
        "sectors. Defensive in panics, constructive in calm trends."
    )
    inspiration = "Atlas — bears the weight of the entire market on his shoulders"
    asset_classes = ("etf",)

    PANIC_VIX = 30.0
    CALM_VIX = 14.0

    def applies_to(self, ctx: AssetContext) -> bool:
        # Override base: ATLAS is even more selective than asset_class alone
        return ctx.ticker in ATLAS_UNIVERSE

    def _judge(self, ctx: AssetContext) -> Verdict:
        signal = Signal.HOLD
        conviction = 0.4
        factors: dict = {}
        reasons: list[str] = []

        vix = ctx.vix

        # Factor 1: VIX panic
        if vix is not None and vix >= self.PANIC_VIX:
            factors["vix_panic"] = vix
            if ctx.ticker in DEFENSIVE_TICKERS:
                signal = Signal.BUY
                conviction = 0.60
                reasons.append(f"VIX {vix:.0f} → flight to defensives")
            elif ctx.ticker in EQUITY_BROAD:
                signal = Signal.SELL
                conviction = 0.55
                reasons.append(f"VIX {vix:.0f} → reduce broad equity exposure")

        # Factor 2: VIX calm + clean trend on broad equity
        elif (
            vix is not None
            and vix < self.CALM_VIX
            and ctx.ticker in EQUITY_BROAD
            and ctx.price and ctx.sma_50 and ctx.sma_200
            and ctx.price > ctx.sma_50 > ctx.sma_200
        ):
            factors["calm_uptrend"] = True
            signal = Signal.BUY
            conviction = 0.50
            reasons.append(f"VIX {vix:.1f}, clean uptrend → constructive")

        # Factor 3: Trend stack alone (less convicted)
        elif (
            ctx.ticker in EQUITY_BROAD
            and ctx.price and ctx.sma_50 and ctx.sma_200
            and ctx.price > ctx.sma_50 > ctx.sma_200
        ):
            factors["trend_stack"] = True
            signal = Signal.BUY
            conviction = 0.45
            reasons.append("price > 50d > 200d → constructive macro")

        # Factor 4: Trend break
        elif (
            ctx.ticker in EQUITY_BROAD
            and ctx.price and ctx.sma_50 and ctx.sma_200
            and ctx.price < ctx.sma_50 < ctx.sma_200
        ):
            factors["trend_break"] = True
            signal = Signal.SELL
            conviction = 0.45
            reasons.append("price < 50d < 200d → defensive macro")

        if not reasons:
            reasons.append("macro indicators uncommitted")

        rationale = "Macro stance: " + "; ".join(reasons) + "."

        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=signal,
            conviction=self._clamp(conviction),
            rationale=rationale,
            factors=factors,
        )


atlas = Atlas()
