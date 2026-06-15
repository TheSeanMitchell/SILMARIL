"""
silmaril.agents.nomad — The ADR Arbitrageur.

NOMAD watches the same company in two cities. When the US ADR drifts
more than 2% from the home listing, that's pure arbitrage — short the
rich side, buy the cheap. Currency-adjusted, of course, but the core
spread above 2% is meaningful in liquid pairs.

Currently the SILMARIL universe doesn't carry foreign listings, so
NOMAD will abstain on everything by default. The logic is in place for
the day a foreign listing feed is wired in.

Optional upstream field:
  - adr_local_spread_pct: float, (ADR_price - home_price_USD) / home_price_USD
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


# US ADR → home listing pairs (for documentation)
ADR_PAIRS = {
    "BABA": "9988.HK", "TSM": "2330.TW", "SHEL": "SHEL.L", "NVO": "NOVO-B.CO",
    "AZN": "AZN.L", "GSK": "GSK.L", "HSBC": "HSBA.L", "TM": "7203.T",
    "SONY": "6758.T", "NIO": "9866.HK", "BIDU": "9888.HK",
}


class Nomad(Agent):
    codename = "NOMAD"
    specialty = "ADR / Home Listing Arbitrage"
    temperament = (
        "Sees the same asset trade at different prices in different "
        "cities. Doesn't predict — just notices. When the spread is "
        "real, takes the cheap side, sells the rich side, lets the "
        "world re-converge."
    )
    inspiration = "The nomad — at home in two places, tied to neither"
    asset_classes = ("equity",)

    def applies_to(self, ctx: AssetContext) -> bool:
        if ctx.ticker not in ADR_PAIRS:
            return False
        return getattr(ctx, "adr_local_spread_pct", None) is not None

    def _judge(self, ctx: AssetContext) -> Verdict:
        spread = getattr(ctx, "adr_local_spread_pct", 0.0) or 0.0

        if spread >= 0.02:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.SELL,
                conviction=0.60,
                rationale=f"ADR trades {spread:+.1%} above home — overpriced vs home",
                factors={"adr_spread": spread},
            )
        if spread <= -0.02:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.BUY,
                conviction=0.60,
                rationale=f"ADR trades {spread:+.1%} below home — underpriced vs home",
                factors={"adr_spread": spread},
            )

        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=Signal.HOLD,
            conviction=0.0,
            rationale=f"ADR spread {spread:+.1%} inside arb threshold",
            factors={"adr_spread": spread},
        )


nomad = Nomad()
