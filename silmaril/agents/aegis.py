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

v2.0 changes — backtest revealed AEGIS was 44% win rate on 21K calls,
because in backtest mode (no sentiment data) its bullish path was
gated on `sentiment_score > 0.1`, which can never be true. Result:
AEGIS only ever issued SELL signals, systematically biased to the
short side. Fixed by adding a sentiment-optional bullish path that
fires on a clean technical setup alone.

Decision logic:
  1. RISK_OFF regime → bias toward SELL/HOLD across the board
  2. VIX > 30 (panic) → SELL across the board
  3. Price > 5% below 200-day SMA → HOLD (don't catch falling knives)
  4. RSI > 75 + euphoric sentiment → SELL (or RSI > 80 alone if sentiment unavailable)
  5. Clean uptrend stack + calm VIX + positive-or-neutral sentiment → BUY
  6. Otherwise → HOLD
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Aegis(Agent):
    codename = "AEGIS"
    specialty = "Capital Preservation"
    temperament = (
        "Principled and protective. Would rather miss ten opportunities "
        "than lose once. Carries veto power when the team's capital is at risk."
    )
    inspiration = "Captain America — the shield, not the sword"
    asset_classes = ("equity", "etf", "crypto")

    # Thresholds
    PANIC_VIX = 30.0
    CAUTION_VIX = 22.0
    EUPHORIA_RSI = 75.0
    EXTREME_RSI = 80.0                # used when sentiment unavailable
    OVERSOLD_RSI = 30.0
    FALLING_KNIFE_THRESHOLD = -0.05   # price > 5% below 200-day SMA

    def _judge(self, ctx: AssetContext) -> Verdict:
        signal = Signal.HOLD
        conviction = 0.4
        factors: dict = {}
        reasons: list[str] = []

        sent_available = ctx.sentiment_score is not None

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

        # ── Factor 3: Falling-knife check (HOLD, not SELL) ───────
        if ctx.price and ctx.sma_200:
            pct_vs_200 = self._pct_above(ctx.price, ctx.sma_200)
            factors["pct_vs_sma200"] = round(pct_vs_200, 4)
            if pct_vs_200 < self.FALLING_KNIFE_THRESHOLD:
                reasons.append(
                    f"price {abs(pct_vs_200)*100:.1f}% below 200-day SMA — falling knife"
                )
                signal = Signal.HOLD
                conviction = max(conviction, 0.65)

        # ── Factor 4: Euphoria check ─────────────────────────────
        if ctx.rsi_14 is not None:
            if sent_available and ctx.rsi_14 >= self.EUPHORIA_RSI and ctx.sentiment_score > 0.5:
                factors["euphoria"] = {"rsi": ctx.rsi_14, "sentiment": ctx.sentiment_score}
                reasons.append(
                    f"RSI {ctx.rsi_14:.0f} + sentiment {ctx.sentiment_score:+.2f} = euphoric top risk"
                )
                signal = Signal.SELL
                conviction = max(conviction, 0.60)
            elif not sent_available and ctx.rsi_14 >= self.EXTREME_RSI:
                # Backtest fallback: extreme RSI alone is the euphoria signal
                factors["extreme_rsi"] = ctx.rsi_14
                reasons.append(f"RSI {ctx.rsi_14:.0f} extreme — top-risk")
                signal = Signal.SELL
                conviction = max(conviction, 0.55)

        # ── Factor 5: Clean BUY conditions ───────────────────────
        # Now sentiment-optional: if sentiment is available, demand >= 0.1
        # If sentiment is None (backtest), require a stronger technical setup
        if (
            signal == Signal.HOLD
            and conviction < 0.65
            and ctx.price is not None
            and ctx.sma_20 is not None
            and ctx.sma_50 is not None
            and ctx.sma_200 is not None
            and ctx.price > ctx.sma_20 > ctx.sma_50 > ctx.sma_200
            and (ctx.vix is None or ctx.vix < self.CAUTION_VIX)
            and ctx.market_regime != "RISK_OFF"
        ):
            if sent_available:
                if ctx.sentiment_score >= 0.1:
                    factors["uptrend_stack"] = True
                    reasons.append("clean uptrend with calm volatility, sentiment supportive")
                    signal = Signal.BUY
                    conviction = 0.55
            else:
                # Backtest: require slightly more confirmation since no sentiment
                # 1) RSI in a healthy zone (40-65)
                # 2) Price not stretched (within reasonable band of SMA-20)
                rsi = ctx.rsi_14 or 50
                stretch = abs((ctx.price - ctx.sma_20) / ctx.sma_20) if ctx.sma_20 else 0
                if 40 <= rsi <= 65 and stretch < 0.04:
                    factors["uptrend_stack"] = True
                    factors["technical_only"] = True
                    reasons.append(
                        f"clean uptrend, RSI {rsi:.0f}, calm volatility — defensible long"
                    )
                    signal = Signal.BUY
                    conviction = 0.50

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
            stop = round(ctx.price - 1.5 * ctx.atr_14, 2)
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

    @staticmethod
    def _compose_rationale(reasons: list[str], signal: Signal) -> str:
        stance = {
            Signal.BUY: "Cautious constructive: ",
            Signal.SELL: "Defensive posture: ",
            Signal.HOLD: "Holding the line: ",
            Signal.STRONG_BUY: "Rare constructive: ",
            Signal.STRONG_SELL: "Protective exit: ",
        }.get(signal, "")
        joined = "; ".join(reasons)
        return f"{stance}{joined}."


aegis = Aegis()
