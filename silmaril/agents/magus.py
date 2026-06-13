"""
silmaril.agents.magus — The Time Reader.

MAGUS plays seasonal patterns: turn-of-month effects, Santa rally,
sell-in-May, day-of-week biases. These effects are small but
statistically persistent, especially on index-level assets.

Doctor Strange's archetype: reading patterns across time.

Decision logic:
  - Late December on indices → seasonal bullish bias
  - Early-to-mid May on indices → seasonal bearish bias
  - Last trading day of month → bullish bias (turn-of-month effect)
  - Friday in uptrending market → mild bullish bias
  - Abstains when no calendar edge is active
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .base import Agent, AssetContext, Signal, Verdict


INDEX_TICKERS = {"SPY", "QQQ", "DIA", "IWM", "VTI"}


class Magus(Agent):
    codename = "MAGUS"
    specialty = "Seasonality & Time"
    temperament = "Reads patterns across time. History rhymes more than it repeats, but it rhymes."
    inspiration = "Doctor Strange — the reader of timelines"
    asset_classes = ("etf",)

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker.upper() in INDEX_TICKERS

    def _judge(self, ctx: AssetContext) -> Verdict:
        now = datetime.now(timezone.utc)
        month, day, weekday = now.month, now.day, now.weekday()

        signals = []

        # Santa rally window (Dec 20 – Jan 2)
        if (month == 12 and day >= 20) or (month == 1 and day <= 2):
            signals.append(("santa_rally", Signal.BUY, 0.5, "Santa Rally window — late-Dec/early-Jan bullish bias."))

        # Sell-in-May (May 5–31)
        if month == 5 and 5 <= day <= 31:
            signals.append(("sell_in_may", Signal.SELL, 0.45, "Sell-in-May seasonal window — reducing exposure."))

        # Turn-of-month (last 3 days of month + first 2)
        if day >= 28 or day <= 2:
            signals.append(("turn_of_month", Signal.BUY, 0.4, "Turn-of-month effect — modest bullish bias."))

        # Friday in clear uptrend
        if weekday == 4 and ctx.sma_20 and ctx.price and ctx.price > ctx.sma_20:
            signals.append(("friday_drift", Signal.BUY, 0.4, "Friday in uptrend — weekend effect."))

        if not signals:
            return self._abstain(ctx, f"no active seasonal pattern for {ctx.ticker}")

        # Pick the highest-conviction of the active signals
        _, sig, conv, reason = max(signals, key=lambda s: s[2])

        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=sig, conviction=conv,
            rationale=reason,
            factors={"active_patterns": [s[0] for s in signals]},
        )

    def _abstain(self, ctx: AssetContext, reason: str) -> Verdict:
        return Verdict(
            agent=self.codename, ticker=ctx.ticker,
            signal=Signal.ABSTAIN, conviction=0.0, rationale=reason,
        )


magus = Magus()
