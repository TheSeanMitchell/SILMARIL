"""
silmaril.agents.obsidian — The Resource King.

OBSIDIAN evaluates only commodities and resource-related assets: gold,
oil, silver, copper, natural gas, energy ETFs, materials. Its lens
is scarcity, inflation, and sovereign positioning. Black Panther's
archetype: wealth drawn from the earth itself.

Decision logic:
  - Only applies to XLE, XLB, GLD, SLV, USO, UNG, DBC, CPER, and OBSIDIAN-tagged equities
  - Gold strength + weakening dollar → STRONG_BUY gold-adjacent
  - Energy strength + oil momentum → BUY energy
  - Otherwise abstain (outside specialty)
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


OBSIDIAN_UNIVERSE = {
    "XLE", "XLB",                     # Energy, Materials sectors
    "GLD", "SLV", "USO", "UNG",       # Precious metals + oil/gas
    "DBC", "CPER",                    # Broad commodities, copper
    "XOM", "CVX", "COP", "SLB",       # Energy majors
    "FCX", "NEM", "GOLD",             # Mining
}


class Obsidian(Agent):
    codename = "OBSIDIAN"
    specialty = "Commodities & Resources"
    temperament = "Patient hoarder of hard assets. Bets on scarcity and inflation."
    inspiration = "Black Panther — the wealth drawn from the earth"
    asset_classes = ("equity", "etf")

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker.upper() in OBSIDIAN_UNIVERSE or ctx.sector in {"Energy", "Materials", "Commodities"}

    def _judge(self, ctx: AssetContext) -> Verdict:
        if not ctx.price or not ctx.sma_50 or not ctx.sma_200:
            return self._hold(ctx, "insufficient data for commodity thesis")

        trend_up = ctx.price > ctx.sma_50 and ctx.sma_50 > ctx.sma_200
        trend_down = ctx.price < ctx.sma_50 and ctx.sma_50 < ctx.sma_200
        rsi = ctx.rsi_14 or 50
        sent = ctx.sentiment_score or 0

        if trend_up and rsi < 70 and sent >= 0:
            conv = 0.6 + (sent * 0.2)
            entry = ctx.price
            stop = ctx.price * 0.95
            target = ctx.price * 1.12
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=self._clamp(conv),
                rationale=f"Commodity trend intact, RSI {rsi:.0f} healthy, sentiment {sent:+.2f}.",
                factors={"trend": "up", "rsi": round(rsi, 1)},
                suggested_entry=round(entry, 2),
                suggested_stop=round(stop, 2),
                suggested_target=round(target, 2),
                invalidation="Close below SMA-50 breaks commodity thesis.",
            )

        if trend_down:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.5,
                rationale="Resource asset in downtrend below both SMAs.",
                factors={"trend": "down"},
            )

        return self._hold(ctx, "commodity consolidation — no edge")

    def _hold(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.HOLD, conviction=0.3, rationale=reason,
        )


obsidian = Obsidian()
