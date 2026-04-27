"""
silmaril.agents.speck — The Small Thing.

SPECK specializes in what the big agents ignore: small-caps (IWM),
lower-profile sector ETFs, and equities with low article counts. Its
edge is that institutional flows take longer to move small things —
so news that fires a setup can lead price by days, not hours.

Ant-Man's archetype: tiny scale, outsized leverage.

Decision logic:
  - Only evaluates IWM, ARKK, and equities with low mega-cap profile
  - Low article count (< 4) + positive sentiment + price above SMA-50 → BUY
  - High RSI on small-cap name → caution
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


SPECK_UNIVERSE = {"IWM", "ARKK"}
MEGA_CAPS = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    "BRK-B", "JPM", "V", "MA", "JNJ", "UNH", "LLY", "XOM", "CVX",
    "HD", "PG", "KO", "WMT", "COST",
}


class Speck(Agent):
    codename = "SPECK"
    specialty = "Small-Cap & Overlooked"
    temperament = "Tiny scale, outsized leverage. Reads news that big agents dismiss."
    inspiration = "Ant-Man — small is fast"
    asset_classes = ("equity", "etf")

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker.upper() in SPECK_UNIVERSE or ctx.ticker.upper() not in MEGA_CAPS

    def _judge(self, ctx: AssetContext) -> Verdict:
        # SPECK likes when nobody's watching
        if ctx.article_count > 8:
            return self._abstain(ctx, "too much coverage — not a SPECK setup")

        if not ctx.price or not ctx.sma_50:
            return self._abstain(ctx, "need basic trend data")

        trend_ok = ctx.price > ctx.sma_50
        sent = ctx.sentiment_score or 0

        if trend_ok and sent > 0.1 and ctx.article_count >= 1:
            conv = 0.52 + min(sent * 0.3, 0.2)
            entry = ctx.price
            stop = ctx.sma_50
            target = ctx.price + (ctx.price - stop) * 2.5
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=self._clamp(conv),
                rationale=(
                    f"Low coverage ({ctx.article_count} articles) but sentiment {sent:+.2f} "
                    f"and price above SMA-50 — small edge before crowd arrives."
                ),
                factors={"article_count": ctx.article_count, "sentiment": round(sent, 3)},
                suggested_entry=round(entry, 2),
                suggested_stop=round(stop, 2),
                suggested_target=round(target, 2),
                invalidation=f"Close below SMA-50 (${stop:.2f}) or mega-cap-level news coverage.",
            )

        return self._abstain(ctx, "no small-cap edge today")

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


speck = Speck()
