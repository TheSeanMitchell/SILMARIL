"""
silmaril.agents.veil — The Hidden Watcher.

VEIL hunts divergence: moments when price and sentiment disagree. When
the crowd turns bearish but the chart stays firm, or vice versa, VEIL
sees a position the tape hasn't priced in yet. Black Widow's archetype:
reads the room while everyone else watches the fight.

Decision logic:
  - Bullish divergence: price up/flat but sentiment meaningfully negative → SELL
    (crowd optimism is fading faster than price)
  - Bearish divergence: price down but sentiment positive → BUY
    (crowd has already seen the turn coming)
  - Requires sufficient article count to trust sentiment read.
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Veil(Agent):
    codename = "VEIL"
    specialty = "Sentiment Divergence"
    temperament = "Watches the room. Trades on what the crowd feels but the tape hasn't priced."
    inspiration = "Black Widow — the hidden watcher, always reading the room"
    asset_classes = ("equity", "etf")

    MIN_ARTICLES = 4            # below this, sentiment signal isn't reliable
    MEANINGFUL_SENT = 0.25      # |score| threshold for 'meaningful'
    PRICE_DIVERGENCE = 0.01     # 1% minimum price move for divergence to matter

    def _judge(self, ctx: AssetContext) -> Verdict:
        if ctx.article_count < self.MIN_ARTICLES or ctx.sentiment_score is None:
            return self._abstain(ctx, f"{ctx.article_count} articles — need {self.MIN_ARTICLES}+ to read the room")

        price_move = (ctx.change_pct or 0) / 100.0  # normalize to fraction
        sent = ctx.sentiment_score

        # ── Bearish divergence: price up, sentiment sour ─────────
        if price_move > self.PRICE_DIVERGENCE and sent < -self.MEANINGFUL_SENT:
            conv = 0.5 + min(abs(sent), 0.3)
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=conv,
                rationale=(
                    f"Price up {price_move*100:+.1f}% but sentiment {sent:+.2f} across "
                    f"{ctx.article_count} sources — crowd sees trouble the tape hasn't."
                ),
                factors={"price_move": round(price_move, 4), "sentiment": round(sent, 3),
                         "article_count": ctx.article_count},
            )

        # ── Bullish divergence: price down, sentiment warming ────
        if price_move < -self.PRICE_DIVERGENCE and sent > self.MEANINGFUL_SENT:
            conv = 0.5 + min(sent, 0.3)
            entry = ctx.price
            stop = ctx.price * 0.96 if ctx.price else None
            target = ctx.price * 1.08 if ctx.price else None
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=conv,
                rationale=(
                    f"Price down {price_move*100:+.1f}% but sentiment {sent:+.2f} — "
                    f"crowd has seen the turn the tape hasn't confirmed."
                ),
                factors={"price_move": round(price_move, 4), "sentiment": round(sent, 3)},
                suggested_entry=round(entry, 2) if entry else None,
                suggested_stop=round(stop, 2) if stop else None,
                suggested_target=round(target, 2) if target else None,
                invalidation="Sentiment reversal or break of 52-week low invalidates the divergence.",
            )

        return self._abstain(ctx, "price and sentiment aligned — no divergence to trade")

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


veil = Veil()
