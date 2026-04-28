"""NIGHTSHADE — Form 4 insider transaction watcher.

Adapter following SILMARIL agent interface. Reads optional fields off
the AssetContext if upstream wires them in:
    ctx.insider_buys_30d, ctx.insider_sells_30d, ctx.insider_net_dollars_30d

If those fields aren't present on the context, NIGHTSHADE abstains
gracefully — no false signals from missing data.
"""
from __future__ import annotations

from .base import Agent, AssetContext, Verdict, Signal


SKIP_CLASSES = {"crypto", "fx", "commodities", "energy_etf"}


class _NightshadeAgent(Agent):
    codename = "NIGHTSHADE"
    bio = (
        "NIGHTSHADE watches the executives. When three or more insiders "
        "buy in a 30-day window with no offsetting sales, that's a signal "
        "people closer to the books are confident. Same logic in reverse: "
        "cluster selling without buying is a yellow flag."
    )

    def applies_to(self, ctx: AssetContext) -> bool:
        ac = getattr(ctx, "asset_class", "equity")
        if ac in SKIP_CLASSES:
            return False
        # Only votes when actual insider data is wired in
        return (
            getattr(ctx, "insider_buys_30d", None) is not None
            or getattr(ctx, "insider_sells_30d", None) is not None
        )

    def evaluate(self, ctx: AssetContext) -> Verdict:
        buys = getattr(ctx, "insider_buys_30d", 0) or 0
        sells = getattr(ctx, "insider_sells_30d", 0) or 0
        net_dollars = getattr(ctx, "insider_net_dollars_30d", 0) or 0

        if buys >= 3 and sells == 0:
            conv = min(0.85, 0.55 + 0.08 * buys)
            return Verdict(
                agent=self.codename,
                signal=Signal.STRONG_BUY,
                conviction=conv,
                rationale=f"{buys} insider buys / 0 sells last 30d (net ${net_dollars:,.0f})",
            )
        if buys >= 2 and sells <= 1:
            return Verdict(
                agent=self.codename,
                signal=Signal.BUY,
                conviction=0.55,
                rationale=f"{buys} insider buys / {sells} sells last 30d",
            )
        if sells >= 3 and buys == 0:
            return Verdict(
                agent=self.codename,
                signal=Signal.SELL,
                conviction=0.55,
                rationale=f"{sells} insider sells / 0 buys last 30d (net ${net_dollars:,.0f})",
            )

        return Verdict(
            agent=self.codename,
            signal=Signal.HOLD,
            conviction=0.0,
            rationale="no decisive insider cluster in last 30d",
        )


nightshade = _NightshadeAgent()
