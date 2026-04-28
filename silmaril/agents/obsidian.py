"""
silmaril.agents.obsidian — The Resource King.

OBSIDIAN evaluates only commodities and resource-related assets: gold,
oil, silver, copper, natural gas, energy ETFs, materials. Its lens is
scarcity, inflation, and sovereign positioning.

v2.0 changes — backtest revealed OBSIDIAN was 45.5% win rate. The old
logic was "buy commodity uptrends, sell commodity downtrends," but
commodities are notoriously mean-reverting on intermediate timeframes.
A trend-following stance loses systematically because it buys near tops
and sells near bottoms. The fix:
  - On the BUY side: require RSI < 60 (don't buy near overbought tops).
  - On the SELL side: require RSI > 65 AND a real trend break,
    not just any "below both SMAs" condition.
  - Added an explicit MEAN-REVERT BUY: deep oversold (RSI < 30) on
    a commodity is historically a high-quality entry.

Black Panther's archetype: wealth drawn from the earth itself.
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


OBSIDIAN_UNIVERSE = {
    "XLE", "XLB",
    "GLD", "SLV", "USO", "UNG",
    "DBC", "CPER",
    "XOM", "CVX", "COP", "SLB",
    "FCX", "NEM", "GOLD",
}


class Obsidian(Agent):
    codename = "OBSIDIAN"
    specialty = "Commodities & Resources"
    temperament = "Patient hoarder of hard assets. Bets on scarcity and mean-reversion in commodities."
    inspiration = "Black Panther — the wealth drawn from the earth"
    asset_classes = ("equity", "etf")

    DEEP_OVERSOLD = 30
    DEEP_OVERBOUGHT = 70
    BUY_RSI_CEILING = 60
    SELL_RSI_FLOOR = 65

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker.upper() in OBSIDIAN_UNIVERSE or ctx.sector in {"Energy", "Materials", "Commodities"}

    def _judge(self, ctx: AssetContext) -> Verdict:
        if not ctx.price or not ctx.sma_50 or not ctx.sma_200:
            return self._hold(ctx, "insufficient data for commodity thesis")

        rsi = ctx.rsi_14 or 50
        sent = ctx.sentiment_score or 0
        sent_available = ctx.sentiment_score is not None
        trend_up = ctx.price > ctx.sma_50 and ctx.sma_50 > ctx.sma_200
        trend_down = ctx.price < ctx.sma_50 and ctx.sma_50 < ctx.sma_200

        # ── Deep oversold mean-reversion BUY (highest priority) ──
        if rsi < self.DEEP_OVERSOLD:
            entry = ctx.price
            stop = ctx.price * 0.94
            target = ctx.price * 1.10
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.65,
                rationale=f"Commodity deep oversold (RSI {rsi:.0f}) — mean-reversion entry.",
                factors={"rsi": round(rsi, 1), "mode": "mean_revert"},
                suggested_entry=round(entry, 2),
                suggested_stop=round(stop, 2),
                suggested_target=round(target, 2),
                invalidation="Break below recent lows invalidates the bounce thesis.",
            )

        # ── Trend-following BUY (only on healthy trend, not stretched) ──
        sentiment_ok = (not sent_available) or (sent >= 0)
        if trend_up and rsi < self.BUY_RSI_CEILING and sentiment_ok:
            conv = 0.55 + (sent * 0.15 if sent_available else 0)
            entry = ctx.price
            stop = ctx.price * 0.95
            target = ctx.price * 1.10
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=self._clamp(conv),
                rationale=f"Commodity uptrend, RSI {rsi:.0f} not stretched — momentum continuation.",
                factors={"trend": "up", "rsi": round(rsi, 1), "mode": "trend"},
                suggested_entry=round(entry, 2),
                suggested_stop=round(stop, 2),
                suggested_target=round(target, 2),
                invalidation="Close below SMA-50 breaks the uptrend thesis.",
            )

        # ── Mean-revert SELL: deeply overbought regardless of trend ──
        if rsi > self.DEEP_OVERBOUGHT:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.55,
                rationale=f"Commodity overbought (RSI {rsi:.0f}) — mean-reversion sell.",
                factors={"rsi": round(rsi, 1), "mode": "mean_revert"},
            )

        # ── Trend-following SELL (much more selective now) ──
        if trend_down and rsi > self.SELL_RSI_FLOOR:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.5,
                rationale=f"Commodity downtrend with RSI bounce (RSI {rsi:.0f}) — sell rallies.",
                factors={"trend": "down", "rsi": round(rsi, 1)},
            )

        return self._hold(ctx, f"commodity in transition (RSI {rsi:.0f}) — no edge")

    def _hold(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.HOLD, conviction=0.3, rationale=reason,
        )


obsidian = Obsidian()
