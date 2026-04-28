"""
silmaril.agents.barnacle — The 13F Whale Follower.

BARNACLE rides the whales. When 2+ institutional 13F filers initiate
the same position in the same quarter, that's a thesis cluster. Same
in reverse for exits.

Optional upstream field:
  - whale_data: dict with keys
      whales_buying:    list[str] of fund names accumulating
      whales_selling:   list[str] of fund names reducing
      whales_initiating: list[str] of fund names with brand-new positions
      whales_exiting:   list[str] of fund names fully closing

If whale_data isn't wired in, BARNACLE abstains.
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Barnacle(Agent):
    codename = "BARNACLE"
    specialty = "13F Whale Cluster Follower"
    temperament = (
        "Doesn't lead, doesn't drown. Attaches to ships that have "
        "already proven they sail. Looks for clusters — one whale is "
        "noise, three are a thesis."
    )
    inspiration = "The barnacle — small, patient, rides the largest movers"
    asset_classes = ("equity",)

    def _judge(self, ctx: AssetContext) -> Verdict:
        wd = getattr(ctx, "whale_data", None)
        if not wd:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale="no 13F whale data wired in",
                factors={"data_missing": True},
            )

        initiating = wd.get("whales_initiating", []) or []
        buying = wd.get("whales_buying", []) or []
        selling = wd.get("whales_selling", []) or []
        exiting = wd.get("whales_exiting", []) or []

        factors = {
            "n_initiating": len(initiating),
            "n_buying": len(buying),
            "n_selling": len(selling),
            "n_exiting": len(exiting),
        }

        # Strong cluster initiation
        if len(initiating) >= 2:
            sample = ", ".join(initiating[:3])
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.STRONG_BUY,
                conviction=min(0.85, 0.55 + 0.10 * len(initiating)),
                rationale=f"{len(initiating)} whales initiating ({sample})",
                factors=factors,
            )

        # General accumulation
        if len(buying) + len(initiating) >= 3:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.BUY,
                conviction=0.60,
                rationale=f"{len(buying) + len(initiating)} whales accumulating",
                factors=factors,
            )

        # Cluster exit
        if len(exiting) >= 2:
            sample = ", ".join(exiting[:3])
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.SELL,
                conviction=0.60,
                rationale=f"{len(exiting)} whales exiting ({sample})",
                factors=factors,
            )

        # General distribution
        if len(selling) + len(exiting) >= 3:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.SELL,
                conviction=0.50,
                rationale=f"{len(selling) + len(exiting)} whales reducing",
                factors=factors,
            )

        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=Signal.HOLD,
            conviction=0.0,
            rationale="no decisive whale cluster",
            factors=factors,
        )


barnacle = Barnacle()
