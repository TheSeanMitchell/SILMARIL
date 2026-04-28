"""
silmaril.agents.nightshade — The Insider Watcher.

NIGHTSHADE only watches one thing: SEC Form 4 filings. When 3+ company
insiders buy in a 30-day window with no offsetting sales, that's a
cluster signal. Same logic in reverse for sells.

Wired-upstream fields (optional on AssetContext):
  - insider_buys_30d:   int, count of insider buys last 30 days
  - insider_sells_30d:  int, count of insider sells last 30 days
  - insider_net_dollars_30d: float, net dollar value (buys - sells)

If these fields aren't present on the context, NIGHTSHADE abstains
gracefully — no false signals from missing data.
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Nightshade(Agent):
    codename = "NIGHTSHADE"
    specialty = "Form 4 Insider Cluster Detection"
    temperament = (
        "Patient, watches the executives. Believes the people closest "
        "to the books know things the market doesn't yet. Stays silent "
        "until cluster activity is unambiguous."
    )
    inspiration = "The deadly nightshade — quiet, watchful, decisive"
    asset_classes = ("equity",)

    def _judge(self, ctx: AssetContext) -> Verdict:
        buys = getattr(ctx, "insider_buys_30d", None)
        sells = getattr(ctx, "insider_sells_30d", None)
        net = getattr(ctx, "insider_net_dollars_30d", None)

        # If no insider data wired in, abstain rather than guess
        if buys is None and sells is None:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale="no insider transaction data available",
                factors={"data_missing": True},
            )

        buys = buys or 0
        sells = sells or 0
        factors = {"buys_30d": buys, "sells_30d": sells}
        if net is not None:
            factors["net_dollars_30d"] = net

        # Strong cluster buy
        if buys >= 3 and sells == 0:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.STRONG_BUY,
                conviction=min(0.85, 0.55 + 0.08 * buys),
                rationale=f"{buys} insider buys, 0 sells in 30d — strong cluster",
                factors=factors,
            )

        # Mild cluster buy
        if buys >= 2 and sells <= 1:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.BUY,
                conviction=0.55,
                rationale=f"{buys} insider buys vs {sells} sells in 30d",
                factors=factors,
            )

        # Cluster sell
        if sells >= 3 and buys == 0:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.SELL,
                conviction=0.55,
                rationale=f"{sells} insider sells, 0 buys in 30d — distribution",
                factors=factors,
            )

        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=Signal.HOLD,
            conviction=0.0,
            rationale=f"no decisive insider cluster ({buys}b/{sells}s)",
            factors=factors,
        )


nightshade = Nightshade()
