"""BARNACLE — 13F whale follower.

Reads ctx.whale_data when wired upstream. Otherwise abstains.
"""
from __future__ import annotations

from .base import Agent, AssetContext, Verdict, Signal


WHALE_CIKS = {
    "BERKSHIRE": "0001067983", "PERSHING_SQUARE": "0001336528",
    "BRIDGEWATER": "0001350694", "RENAISSANCE": "0001037389",
    "BAUPOST": "0001061165", "GREENLIGHT": "0001079114",
    "SOROS": "0001029160", "TIGER_GLOBAL": "0001167483",
    "LONE_PINE": "0001061768", "COATUE": "0001135730",
    "TWO_SIGMA": "0001179392", "AQR": "0001167557",
}

SKIP_CLASSES = {"crypto", "fx", "commodities", "token"}


class _BarnacleAgent(Agent):
    codename = "BARNACLE"
    bio = (
        "BARNACLE rides the whales. When two or more 13F filers initiate "
        "the same position in the same quarter, that's a thesis cluster. "
        "Followers don't lead, but they don't drown either."
    )

    def applies_to(self, ctx: AssetContext) -> bool:
        if getattr(ctx, "asset_class", "equity") in SKIP_CLASSES:
            return False
        wd = getattr(ctx, "whale_data", None)
        return bool(wd)

    def evaluate(self, ctx: AssetContext) -> Verdict:
        wd = getattr(ctx, "whale_data", {}) or {}
        initiating = wd.get("whales_initiating", []) or []
        buying = wd.get("whales_buying", []) or []
        selling = wd.get("whales_selling", []) or []
        exiting = wd.get("whales_exiting", []) or []

        if len(initiating) >= 2:
            return Verdict(
                agent=self.codename, signal=Signal.STRONG_BUY,
                conviction=min(0.85, 0.55 + 0.10 * len(initiating)),
                rationale=f"{len(initiating)} whales initiating ({', '.join(initiating[:3])})",
            )
        if (len(buying) + len(initiating)) >= 3:
            return Verdict(
                agent=self.codename, signal=Signal.BUY, conviction=0.60,
                rationale=f"{len(buying)+len(initiating)} whales accumulating",
            )
        if len(exiting) >= 2:
            return Verdict(
                agent=self.codename, signal=Signal.SELL, conviction=0.60,
                rationale=f"{len(exiting)} whales exiting ({', '.join(exiting[:3])})",
            )
        if (len(selling) + len(exiting)) >= 3:
            return Verdict(
                agent=self.codename, signal=Signal.SELL, conviction=0.50,
                rationale=f"{len(selling)+len(exiting)} whales reducing",
            )

        return Verdict(
            agent=self.codename, signal=Signal.HOLD, conviction=0.0,
            rationale="no decisive whale cluster",
        )


barnacle = _BarnacleAgent()
