"""CICADA — earnings whisper / pre-earnings drift trader.

Only votes when ctx.days_to_earnings is within 7. Looks for cases where
the whisper number diverges from consensus and price hasn't yet repriced.
Falls back to no-vote if whisper data isn't wired upstream.
"""
from __future__ import annotations

from .base import Agent, AssetContext, Verdict, Signal


SKIP_CLASSES = {"crypto", "fx", "commodities"}


class _CicadaAgent(Agent):
    codename = "CICADA"
    bio = (
        "CICADA only sings the week before earnings. When the whisper "
        "number floats meaningfully above consensus and the stock hasn't "
        "moved, that's an asymmetric setup. CICADA stays silent the "
        "other 51 weeks of the year."
    )

    def applies_to(self, ctx: AssetContext) -> bool:
        if getattr(ctx, "asset_class", "equity") in SKIP_CLASSES:
            return False
        d2e = getattr(ctx, "days_to_earnings", None)
        return d2e is not None and 0 <= d2e <= 7

    def evaluate(self, ctx: AssetContext) -> Verdict:
        d2e = getattr(ctx, "days_to_earnings", None)
        consensus = getattr(ctx, "consensus_eps", None)
        whisper = getattr(ctx, "whisper_eps", None)
        wk_change = getattr(ctx, "week_change_pct", None)

        # If we have whisper data and price hasn't run, lean directional
        if consensus and whisper and wk_change is not None:
            if consensus > 0:
                whisper_premium = (whisper - consensus) / abs(consensus)
            else:
                whisper_premium = 0.0
            if whisper_premium > 0.05 and wk_change < 2.0:
                return Verdict(
                    agent=self.codename,
                    signal=Signal.BUY,
                    conviction=0.65,
                    rationale=(
                        f"earnings in {d2e}d, whisper {whisper_premium:+.0%} "
                        f"vs consensus, wk move {wk_change:+.1f}% — undriftd"
                    ),
                )
            if whisper_premium < -0.05 and wk_change > -2.0:
                return Verdict(
                    agent=self.codename,
                    signal=Signal.SELL,
                    conviction=0.55,
                    rationale=(
                        f"earnings in {d2e}d, whisper {whisper_premium:+.0%} "
                        f"vs consensus, wk move {wk_change:+.1f}% — soft setup"
                    ),
                )

        # Fallback: just flag the proximity, conviction zero
        return Verdict(
            agent=self.codename,
            signal=Signal.HOLD,
            conviction=0.0,
            rationale=f"earnings in {d2e}d, awaiting whisper signal",
        )


cicada = _CicadaAgent()
