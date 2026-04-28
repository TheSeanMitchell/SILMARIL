"""
silmaril.agents.vespa — The Catalyst Striker.

VESPA lives around events: earnings, FDA decisions, Fed meetings,
product launches. It takes positions into known catalysts with clear
expectations and exits quickly after the event fires. Wasp's
archetype: fast, precise, event-oriented.

Decision logic:
  - Earnings within 5 days + positive sentiment → BUY
  - Earnings within 5 days + negative sentiment → SELL
  - Event flags (FDA, FOMC, etc.) take priority
  - Abstains when no catalyst is near
"""

from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Vespa(Agent):
    codename = "VESPA"
    specialty = "Event-Driven"
    temperament = "Lives for the catalyst. Strikes fast and precise, leaves before the dust settles."
    inspiration = "The Wasp — small, quick, event-oriented"
    asset_classes = ("equity",)

    EVENT_WINDOW = 5           # days to catalyst

    def _judge(self, ctx: AssetContext) -> Verdict:
        # ── Event flag overrides earnings proximity ─────────────
        if ctx.event_flags:
            return self._event_flag_verdict(ctx)

        days = ctx.days_to_earnings
        if days is None or days < 0 or days > self.EVENT_WINDOW:
            return self._abstain(ctx, "no catalyst in window")

        sent = ctx.sentiment_score or 0
        articles = ctx.article_count

        if articles < 2:
            return self._abstain(ctx, f"earnings in {days}d but insufficient news flow")

        # Directional bet sized by sentiment
        if sent > 0.2:
            entry = ctx.price
            stop = ctx.price * 0.93 if ctx.price else None
            target = ctx.price * 1.12 if ctx.price else None
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.BUY, conviction=0.5 + min(sent * 0.3, 0.15),
                rationale=f"Earnings in {days}d with positive sentiment {sent:+.2f} — lean long.",
                factors={"days_to_earnings": days, "sentiment": round(sent, 3)},
                suggested_entry=round(entry, 2) if entry else None,
                suggested_stop=round(stop, 2) if stop else None,
                suggested_target=round(target, 2) if target else None,
                invalidation="Exit before or immediately after earnings — not a long-term thesis.",
            )

        if sent < -0.2:
            return Verdict(
                agent=self.codename, ticker=ctx.ticker,
                signal=Signal.SELL, conviction=0.5 + min(abs(sent) * 0.3, 0.15),
                rationale=f"Earnings in {days}d with negative sentiment {sent:+.2f} — lean short.",
                factors={"days_to_earnings": days, "sentiment": round(sent, 3)},
            )

        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.HOLD, conviction=0.4,
            rationale=f"Earnings in {days}d but sentiment {sent:+.2f} mixed — no directional edge.",
        )

    def _event_flag_verdict(self, ctx: AssetContext) -> Verdict:
        flag = ctx.event_flags[0]
        sent = ctx.sentiment_score or 0
        sig = Signal.BUY if sent > 0 else (Signal.SELL if sent < 0 else Signal.HOLD)
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=sig, conviction=0.55,
            rationale=f"Active event flag '{flag}' with sentiment {sent:+.2f} — tactical positioning.",
            factors={"event_flag": flag, "sentiment": round(sent, 3)},
        )

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


vespa = Vespa()
