"""NOMAD — ADR / home-listing arbitrage signal.

Currently the SILMARIL universe doesn't carry foreign listings, so NOMAD
abstains on everything by default. The logic is here for when a foreign
spread feed is wired in via ctx.adr_local_spread_pct.
"""
from __future__ import annotations

from .base import Agent, AssetContext, Verdict, Signal


ADR_PAIRS = {
    "BABA": "9988.HK", "TSM": "2330.TW", "SHEL": "SHEL.L", "NVO": "NOVO-B.CO",
    "AZN": "AZN.L", "GSK": "GSK.L", "HSBC": "HSBA.L", "TM": "7203.T",
    "SONY": "6758.T", "NIO": "9866.HK", "BIDU": "9888.HK",
}


class _NomadAgent(Agent):
    codename = "NOMAD"
    bio = (
        "NOMAD watches the same company in two cities. When the US ADR "
        "drifts >2% from the home listing, that's pure arbitrage — short "
        "the rich side, buy the cheap. Only votes when an ADR/home spread "
        "feed is wired in."
    )

    def applies_to(self, ctx: AssetContext) -> bool:
        if ctx.ticker not in ADR_PAIRS:
            return False
        return getattr(ctx, "adr_local_spread_pct", None) is not None

    def evaluate(self, ctx: AssetContext) -> Verdict:
        spread = getattr(ctx, "adr_local_spread_pct", 0.0) or 0.0
        if spread >= 0.02:
            return Verdict(
                agent=self.codename, signal=Signal.SELL, conviction=0.60,
                rationale=f"ADR trades {spread:+.1%} above home listing — overpriced vs home",
            )
        if spread <= -0.02:
            return Verdict(
                agent=self.codename, signal=Signal.BUY, conviction=0.60,
                rationale=f"ADR trades {spread:+.1%} below home listing — underpriced vs home",
            )
        return Verdict(
            agent=self.codename, signal=Signal.HOLD, conviction=0.0,
            rationale=f"ADR spread {spread:+.1%} inside arb threshold",
        )


nomad = _NomadAgent()
