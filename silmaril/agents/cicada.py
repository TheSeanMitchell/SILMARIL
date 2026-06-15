"""
silmaril.agents.cicada — The Earnings Whisperer.

CICADA only sings the week before an earnings release. The other 51
weeks of the year, it stays silent (ABSTAIN). When earnings is within
7 days, it looks for setups where:
  - The whisper number floats above consensus AND price hasn't moved
  - Or whisper below consensus AND price hasn't sold off

This is a pre-earnings drift trade — riding the gravity of the surprise
before the surprise happens.

Optional context fields:
  - days_to_earnings: int   (already in AssetContext)
  - consensus_eps: float    (wired upstream)
  - whisper_eps: float      (wired upstream — Estimize, etc.)
  - week_change_pct: float  (wired upstream — last 5 trading days)
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Cicada(Agent):
    codename = "CICADA"
    specialty = "Pre-Earnings Drift Trader"
    temperament = (
        "Silent for 51 weeks. Sings the week before earnings. Looks for "
        "asymmetric setups where the whisper diverges from consensus "
        "and price hasn't repriced yet. Disappears the moment earnings "
        "report — never holds through the announcement."
    )
    inspiration = "The cicada — emerges only when conditions are exactly right"
    asset_classes = ("equity",)

    def _judge(self, ctx: AssetContext) -> Verdict:
        d2e = ctx.days_to_earnings

        # Outside the earnings window — fully silent
        if d2e is None or d2e < 0 or d2e > 7:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale="not within 7 days of earnings",
            )

        # Need whisper + consensus for full signal
        consensus = getattr(ctx, "consensus_eps", None)
        whisper = getattr(ctx, "whisper_eps", None)
        wk_change = getattr(ctx, "week_change_pct", None)

        if consensus and whisper and wk_change is not None and consensus != 0:
            premium = (whisper - consensus) / abs(consensus)

            if premium > 0.05 and wk_change < 2.0:
                return Verdict(
                    agent=self.codename,
                    ticker=ctx.ticker,
                    signal=Signal.BUY,
                    conviction=0.65,
                    rationale=(
                        f"earnings in {d2e}d, whisper {premium:+.0%} "
                        f"vs consensus, week move {wk_change:+.1f}% "
                        f"— undriftd setup"
                    ),
                    factors={
                        "days_to_earnings": d2e,
                        "whisper_premium": round(premium, 4),
                        "week_change_pct": wk_change,
                    },
                )

            if premium < -0.05 and wk_change > -2.0:
                return Verdict(
                    agent=self.codename,
                    ticker=ctx.ticker,
                    signal=Signal.SELL,
                    conviction=0.55,
                    rationale=(
                        f"earnings in {d2e}d, whisper {premium:+.0%} "
                        f"vs consensus, week move {wk_change:+.1f}% "
                        f"— soft setup"
                    ),
                    factors={
                        "days_to_earnings": d2e,
                        "whisper_premium": round(premium, 4),
                        "week_change_pct": wk_change,
                    },
                )

        # In-window but no whisper data → just flag proximity, no vote
        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=Signal.HOLD,
            conviction=0.0,
            rationale=f"earnings in {d2e}d, awaiting whisper signal",
            factors={"days_to_earnings": d2e},
        )


cicada = Cicada()
