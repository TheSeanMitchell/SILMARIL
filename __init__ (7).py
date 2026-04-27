"""
silmaril.agents.synth — The Synthesist.

SYNTH looks across markets for correlation signals: risk-off rotations
(bonds up + equities down), dollar strength affecting commodities,
sector rotations within the index. Its edge is reading what's moving
with what — and what isn't.

Vision's archetype: synthetic being that perceives patterns across systems.

Decision logic:
  - Watches SPY, TLT, GLD, UUP, VIX as macro references
  - Risk-off rotation (TLT up, SPY down) → SELL equities, BUY bonds
  - Dollar weakness (UUP down) → BUY gold/commodity equities
  - Equity-defensive rotation → bias toward staples, utilities, healthcare
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

        is_defensive = ctx.ticker.upper() in MACRO_DEFENSIVES or ctx.sector in {"Staples", "Utilities", "Healthcare"}
        is_risk = ctx.ticker.upper() in MACRO_RISK or ctx.sector in {"Technology", "Discretionary"}

        # ── Risk-off regime: favor defensives ───────────────────
        if regime == "RISK_OFF":
            if is_defensive:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.6,
                    rationale="Risk-off rotation — defensive positioning favored.",
                    factors={"regime": regime, "is_defensive": True},
                    suggested_entry=ctx.price, suggested_stop=None,
                )
            if is_risk:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.SELL, conviction=0.55,
                    rationale="Risk-off rotation — reducing cyclical exposure.",
                    factors={"regime": regime, "is_risk": True},
                )

        # ── Risk-on regime: favor cyclicals ─────────────────────
        if regime == "RISK_ON":
            if is_risk and sent >= 0:
                return Verdict(
                    agent=self.codename, ticker=ctx.ticker,
                    signal=Signal.BUY, conviction=0.5,
                    rationale="Risk-on regime supports cyclical exposure.",
                    factors={"regime": regime, "is_risk": True},
                )

        return self._abstain(ctx, f"regime {regime} — no cross-market edge")

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


synth = Synth()
