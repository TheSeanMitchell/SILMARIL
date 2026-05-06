"""
silmaril.agents.candidate_beta — BETA, the Short Squeeze Hunter.

BETA watches the tension between short sellers and the tape.
Two signals:
  1. FINRA short volume ratio — when shorted volume is very high AND
     price starts rising, a squeeze becomes possible.
  2. CBOE single-stock put/call ratio — extreme put buying (fear) can
     be a contrarian buy signal when paired with price stabilization.

BETA is contrarian but disciplined. He doesn't buy just because shorts
are high — he waits for the turn. A stock that's 45% short with
RSI turning up from oversold is his sweet spot.

CANDIDATE — shadow mode. Calls scored, no consensus influence yet.

Data sources:
  silmaril.ingestion.finra_short (FINRA daily short volume, free, public)
  silmaril.ingestion.cboe (CBOE daily P/C ratio, free, public)
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict

try:
    from silmaril.ingestion.finra_short import get_short_ratio
    _HAS_FINRA = True
except Exception:
    _HAS_FINRA = False
    def get_short_ratio(ticker: str) -> float: return 0.0

try:
    from silmaril.ingestion.cboe import get_put_call_ratio
    _HAS_CBOE = True
except Exception:
    _HAS_CBOE = False
    def get_put_call_ratio(ticker: str = "SPX") -> float: return 1.0


class CandidateBeta(Agent):
    codename    = "CANDIDATE_BETA"
    specialty   = "Short squeeze pressure + CBOE put/call contrarian"
    temperament = (
        "Contrarian. Loves the stocks that the market hates the most — "
        "right when the hate is about to unwind."
    )
    inspiration = "David vs Goliath. The short seller IS Goliath."
    asset_classes = ("equity",)

    def applies_to(self, ctx: AssetContext) -> bool:
        return (ctx.asset_class or "equity") == "equity" and "-USD" not in ctx.ticker

    def _judge(self, ctx: AssetContext) -> Verdict:
        ticker = ctx.ticker
        price  = ctx.price
        rsi    = ctx.rsi_14 or 50.0
        chg    = ctx.change_pct or 0.0

        short_ratio = get_short_ratio(ticker) if _HAS_FINRA else 0.0
        pc_ratio    = get_put_call_ratio(ticker) if _HAS_CBOE else 1.0

        # Short ratio: 0.0–1.0 (fraction of volume that was short)
        # PC ratio: >1.5 = extreme fear (contrarian buy), <0.7 = extreme greed

        high_short   = short_ratio > 0.40   # more than 40% of vol is short
        turning_up   = chg > 0.5 and rsi < 65   # price turning, not yet overbought
        extreme_fear = pc_ratio > 1.5
        oversold     = rsi < 35

        # Perfect squeeze setup: high short + price turning + extreme fear
        if high_short and turning_up and extreme_fear:
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.STRONG_BUY, conviction=0.80,
                rationale=(
                    f"SQUEEZE SETUP: short ratio {short_ratio:.0%}, "
                    f"P/C {pc_ratio:.2f} (extreme fear), price turning +{chg:.1f}% "
                    f"with RSI {rsi:.0f}. BETA smells blood in the water."
                ),
                factors={"short_ratio": round(short_ratio, 3),
                         "pc_ratio": round(pc_ratio, 2), "rsi": round(rsi, 1)},
                suggested_entry=round(price, 2) if price else None,
                suggested_stop=round(price * 0.94, 2) if price else None,
                suggested_target=round(price * 1.20, 2) if price else None,
                invalidation="Close below entry -6% means squeeze failed.",
            )

        # High short + oversold — potential coil, buy the base
        if high_short and oversold:
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.BUY, conviction=0.60,
                rationale=(
                    f"High short ratio ({short_ratio:.0%}) + RSI {rsi:.0f} oversold. "
                    f"BETA enters the coil, waits for the spring."
                ),
                factors={"short_ratio": round(short_ratio, 3), "rsi": round(rsi, 1)},
            )

        # Extreme fear as contrarian buy (index-level)
        if extreme_fear and pc_ratio > 1.8 and oversold:
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.BUY, conviction=0.55,
                rationale=(
                    f"P/C ratio {pc_ratio:.2f} signals extreme fear. "
                    f"BETA takes the other side of the panic."
                ),
                factors={"pc_ratio": round(pc_ratio, 2)},
            )

        # High short but no turn yet — watch, don't chase
        if high_short and not turning_up:
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.HOLD, conviction=0.45,
                rationale=(
                    f"High short ({short_ratio:.0%}) but no price turn yet. "
                    f"BETA watches. He doesn't catch falling knives."
                ),
            )

        return Verdict(
            agent=self.codename, ticker=ticker,
            signal=Signal.HOLD, conviction=0.35,
            rationale="No squeeze or fear signal. BETA passes.",
        )


candidate_beta = CandidateBeta()
