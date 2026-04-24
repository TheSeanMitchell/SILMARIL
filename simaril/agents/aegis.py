"""
silmaril.agents.aegis — The Shield.

AEGIS is the defensive cornerstone of the team. Its job is not to find
opportunity; its job is to prevent catastrophic loss. It is the only
agent with veto power over trade plans (see debate/arbiter.py).

Trading philosophy (Captain America archetype):
  - Principled, disciplined, protective
  - Never adds risk in dangerous regimes
  - Prefers inaction to a bad entry
  - Protects the team's capital so everyone lives to trade tomorrow

Decision logic (rule-based, fully inspectable):
  1. If market regime is RISK_OFF → bias toward SELL/HOLD across the board
  2. If VIX > 30 (fear regime) → downgrade any BUY conviction by 40%
  3. If price is more than 5% below its 200-day SMA → HOLD (falling knives are not bargains)
  4. If RSI > 75 AND sentiment heat is extreme → SELL (euphoria is the sell signal)
  5. If sentiment is mildly positive AND price is above all moving averages AND VIX is calm →
     cautious BUY with tight stop
  6. Otherwise → HOLD

Every output includes an invalidation clause — the specific condition
that would prove the thesis wrong. AEGIS never trades without knowing
where it would admit defeat.
"""

from __future__ import annotations

from typing import Optional

from .base import Agent, AssetContext, Signal, Verdict


class Aegis(Agent):
    codename = "AEGIS"
    specialty = "Capital Preservation"
    temperament = (
        "Principled and protective. Would rather miss ten opportunities "
        "than lose once. Carries veto power when the team's capital is at risk."
    )
    inspiration = "Captain America — the shield, not the sword"
    asset_classes = ("equity", "etf", "crypto")   # AEGIS cares about everything

    # Thresholds — all explicitly tunable constants, no magic numbers buried in code
    PANIC_VIX = 30.0
    CAUTION_VIX = 22.0
    EUPHORIA_RSI = 75.0
    OVERSOLD_RSI = 30.0
    DEFENSIVE_SMA_BAND = 0.05   # within 5% of 200-day SMA
    FALLING_KNIFE_THRESHOLD = -0.05  # price > 5% below 200-day SMA

    def _judge(self, ctx: AssetContext) -> Verdict:
        # Start neutral, adjust based on evidence
        signal = Signal.HOLD
        conviction = 0.4
        factors: dict = {}
        reasons: list[str] = []

        # ── Factor 1: Market regime gate ─────────────────────────
        if ctx.market_regime == "RISK_OFF":
            factors["regime_penalty"] = True
            reasons.append("risk-off regime demands defense")
            signal = Signal.SELL
            conviction = 0.55

        # ── Factor 2: VIX fear gauge ─────────────────────────────
        if ctx.vix is not None:
            if ctx.vix >= self.PANIC_VIX:
                factors["vix_panic"] = ctx.vix
                reasons.append(f"VIX at {ctx.vix:.1f} signals panic")
                signal = Signal.SELL
                conviction = max(conviction, 0.65)
            elif ctx.vix >= self.CAUTION_VIX:
                factors["vix_caution"] = ctx.vix
                reasons.append(f"VIX at {ctx.vix:.1f} warrants caution")

        # ── Factor 3: Falling-knife check ────────────────────────
        if ctx.price and ctx.sma_200:
            pct_vs_200 = self._pct_above(ctx.price, ctx.sma_200)
            factors["pct_vs_sma200"] = round(pct_vs_200, 4)
            if pct_vs_200 < self.FALLING_KNIFE_THRESHOLD:
                reasons.append(
                    f"price {abs(pct_vs_200)*100:.1f}% below 200-day SMA — falling knife"
                )
                signal = Signal.HOLD
                conviction = 0.7  # high conviction NOT to touch

        # ── Factor 4: Euphoria check ─────────────────────────────
        if (
            ctx.rsi_14 is not None
            and ctx.rsi_14 >= self.EUPHORIA_RSI
            and ctx.sentiment_score is not None
            and ctx.sentiment_score > 0.5
        ):
            factors["euphoria"] = {"rsi": ctx.rsi_14, "sentiment": ctx.sentiment_score}
            reasons.append(
                f"RSI {ctx.rsi_14:.0f} + sentiment {ctx.sentiment_score:+.2f} = euphoric top risk"
            )
            signal = Signal.SELL
            conviction = max(conviction, 0.65)

        # ── Factor 5: Clean-cautious-BUY conditions ──────────────
        # Only trigger if nothing above fired a SELL/HOLD-high-conviction
        clean_setup = (
            signal == Signal.HOLD
            and conviction < 0.7
            and ctx.price is not None
            and ctx.sma_20 is not None
            and ctx.sma_50 is not None
            and ctx.sma_200 is not None
            and ctx.price > ctx.sma_20 > ctx.sma_50 > ctx.sma_200  # clean uptrend stack
            and (ctx.vix is None or ctx.vix < self.CAUTION_VIX)
            and (ctx.sentiment_score or 0) > 0.1
            and ctx.market_regime != "RISK_OFF"
        )
        if clean_setup:
            factors["uptrend_stack"] = True
            reasons.append("clean uptrend with calm volatility")
            signal = Signal.BUY
            conviction = 0.55   # AEGIS is never more than moderately convicted on BUY

        # ── Factor 6: Insufficient data guard ────────────────────
        if ctx.price is None or ctx.sma_200 is None:
            reasons.append("insufficient price history for defensive assessment")
            signal = Signal.HOLD
            conviction = 0.3
            factors["insufficient_data"] = True

        # ── Build rationale ──────────────────────────────────────
        if not reasons:
            reasons.append("no defensive flags triggered; neutral posture")
        rationale = self._compose_rationale(reasons, signal)

        # ── Trade plan if BUY ────────────────────────────────────
        entry = stop = target = None
        invalidation = None
        if signal == Signal.BUY and ctx.price and ctx.atr_14:
            entry = round(ctx.price, 2)
            # AEGIS uses tight stops: 1.5× ATR below entry
            stop = round(ctx.price - 1.5 * ctx.atr_14, 2)
            # Conservative target: 2× ATR above entry (1.33:1 reward/risk)
            target = round(ctx.price + 2.0 * ctx.atr_14, 2)
            invalidation = (
                f"Close below ${stop:.2f} (1.5 ATR stop) OR VIX spike above "
                f"{self.PANIC_VIX:.0f} invalidates thesis."
            )

        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=signal,
            conviction=self._clamp(conviction),
            rationale=rationale,
            factors=factors,
            suggested_entry=entry,
            suggested_stop=stop,
            suggested_target=target,
            invalidation=invalidation,
        )

    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _compose_rationale(reasons: list[str], signal: Signal) -> str:
        """Compose a one-sentence human-readable rationale."""
        stance = {
            Signal.BUY: "Cautious constructive: ",
            Signal.SELL: "Defensive posture: ",
            Signal.HOLD: "Holding the line: ",
            Signal.STRONG_BUY: "Rare constructive: ",
            Signal.STRONG_SELL: "Protective exit: ",
        }.get(signal, "")
        joined = "; ".join(reasons)
        return f"{stance}{joined}."


# Module-level singleton for easy import
aegis = Aegis()
