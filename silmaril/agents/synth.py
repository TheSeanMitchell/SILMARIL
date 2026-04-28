"""
silmaril.agents.synth — The Synthesist.

SYNTH looks across markets for correlation and rotation signals. Its
edge is reading what's moving with what — and what isn't. Vision's
archetype: synthetic perception across systems.

v2.0 changes — backtest revealed SYNTH was 50.1% win rate. The old
logic only voted on RISK_ON or RISK_OFF regimes, abstaining on
NEUTRAL. But the regime classifier produces NEUTRAL roughly half
the time, so SYNTH was sitting out half the market. Fixed by:
  - Adding NEUTRAL-regime logic: bias slightly defensive when VIX is
    elevated (>20) even in NEUTRAL, slightly long-cyclical when calm.
  - Tightening BUY conditions: requires sentiment >= 0 OR sentiment
    unavailable AND momentum positive.
  - SELL conditions now also require some technical confirmation, not
    just regime tag.
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


MACRO_DEFENSIVES = {"XLP", "XLU", "XLV", "GLD", "SLV", "TLT"}
MACRO_RISK = {"SPY", "QQQ", "IWM", "XLK", "XLY", "XLF"}


class Synth(Agent):
    codename = "SYNTH"
    specialty = "Cross-Market Correlation"
    temperament = "Synthesizes signals across markets. Reads the rotation the crowd misses."
    inspiration = "Vision — synthetic perception across systems"
    asset_classes = ("equity", "etf")

    def _judge(self, ctx: AssetContext) -> Verdict:
        regime = ctx.market_regime
        sent = ctx.sentiment_score or 0
        sent_available = ctx.sentiment_score is not None
        vix = ctx.vix or 18.0

        is_defensive = (
            ctx.ticker.upper() in MACRO_DEFENSIVES
            or ctx.sector in {"Staples", "Utilities", "Healthcare"}
        )
        is_risk = (
            ctx.ticker.upper() in MACRO_RISK
            or ctx.sector in {"Technology", "Discretionary"}
        )

        if not (is_defensive or is_risk):
            return self._abstain(ctx, "not in cross-market rotation universe")

        # Compute short momentum signal
        ph = ctx.price_history or []
        mom_10d = None
        if len(ph) >= 11 and ph[-11] > 0:
            mom_10d = (ctx.price / ph[-11]) - 1.0

        # ── RISK_OFF regime ──────────────────────────────────────
        if regime == "RISK_OFF":
            if is_defensive:
                conv = 0.60 + min(vix - 25, 5) * 0.01 if vix > 25 else 0.55
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=self._clamp(conv),
                    rationale=f"Risk-off regime, VIX {vix:.0f} — defensive rotation.",
                    factors={"regime": regime, "vix": vix},
                )
            if is_risk and (mom_10d is None or mom_10d <= 0):
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.SELL, conviction=0.55,
                    rationale="Risk-off regime — reducing cyclical exposure.",
                    factors={"regime": regime},
                )

        # ── RISK_ON regime ────────────────────────────────────────
        if regime == "RISK_ON":
            sent_ok = (not sent_available) or (sent >= 0)
            if is_risk and sent_ok and (mom_10d is None or mom_10d >= 0):
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.55,
                    rationale="Risk-on regime supports cyclical exposure.",
                    factors={"regime": regime},
                )

        # ── NEUTRAL regime: VIX-tilted ────────────────────────────
        if regime == "NEUTRAL":
            if vix >= 22 and is_defensive:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.50,
                    rationale=f"Neutral regime but VIX {vix:.0f} elevated — defensive lean.",
                    factors={"regime": regime, "vix": vix},
                )
            if vix < 16 and is_risk and (mom_10d is None or mom_10d > 0):
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.45,
                    rationale=f"Neutral regime, VIX {vix:.0f} calm — cyclical lean.",
                    factors={"regime": regime, "vix": vix},
                )

        return self._abstain(ctx, f"regime {regime} — no cross-market edge")

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


synth = Synth()
