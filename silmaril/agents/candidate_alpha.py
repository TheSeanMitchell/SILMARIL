"""
silmaril.agents.candidate_alpha — ALPHA, the Insider Flow Tracker.

ALPHA watches what insiders actually do with their own money.
SEC Form 4 filings are public within 2 business days of a transaction.
When an insider buys significant shares at market price (not options, not
gifts), that's the strongest legal leading indicator available.

ALPHA combines:
  1. SEC EDGAR Form 4 insider purchase volume (rolling 30-day)
  2. Price momentum (SMA crossover confirmation)
  3. Rejects: options exercises, sales, gifts, inheritance

ALPHA is a CANDIDATE — shadow mode. His calls are scored but do not
affect main consensus until he earns promotion through the Senate.

Data source: silmaril.ingestion.form4 (EDGAR EFTS API, free, keyless)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .base import Agent, AssetContext, Signal, Verdict

try:
    from silmaril.ingestion.form4 import get_insider_buy_score
    _HAS_FORM4 = True
except Exception:
    _HAS_FORM4 = False
    def get_insider_buy_score(ticker: str) -> float: return 0.0


class CandidateAlpha(Agent):
    codename    = "CANDIDATE_ALPHA"
    specialty   = "SEC Form 4 insider flow + price momentum"
    temperament = (
        "Follows the smart money. If a CFO is buying 50,000 shares at market "
        "price with their own money, ALPHA wants to know why."
    )
    inspiration = "Peter Lynch: 'Insiders might sell for many reasons, but they only buy for one.'"
    asset_classes = ("equity",)

    def applies_to(self, ctx: AssetContext) -> bool:
        # Only equities — no ETFs, no crypto
        return (ctx.asset_class or "equity") == "equity" and "-USD" not in ctx.ticker

    def _judge(self, ctx: AssetContext) -> Verdict:
        ticker = ctx.ticker
        price  = ctx.price
        sma50  = ctx.sma_50
        sma200 = ctx.sma_200

        # Get insider buy score from Form 4 ingestion
        insider_score = 0.0
        if _HAS_FORM4:
            try:
                insider_score = get_insider_buy_score(ticker)
            except Exception:
                insider_score = 0.0

        # No insider signal and no trend confirmation
        if insider_score <= 0 and (not price or not sma50):
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.HOLD, conviction=0.35,
                rationale="No Form 4 purchases detected. ALPHA watches.",
            )

        # Strong insider buying + uptrend
        if insider_score >= 2.0 and price and sma50 and price > sma50:
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.STRONG_BUY, conviction=0.82,
                rationale=(
                    f"STRONG insider buying (score={insider_score:.1f}) + price above SMA-50. "
                    f"Form 4 filings show meaningful open-market purchases. "
                    f"ALPHA is very interested."
                ),
                factors={"insider_score": insider_score, "above_sma50": True},
                suggested_entry=round(price, 2),
                suggested_stop=round(sma50 * 0.97, 2) if sma50 else None,
                suggested_target=round(price * 1.15, 2),
            )

        # Moderate insider buying + any positive price trend
        if insider_score >= 1.0:
            above_200 = price and sma200 and price > sma200
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.BUY, conviction=0.62,
                rationale=(
                    f"Insider buying detected (score={insider_score:.1f}). "
                    f"{'Above SMA-200 — trend confirms.' if above_200 else 'Below SMA-200 — risk acknowledged.'} "
                    f"ALPHA opens a position."
                ),
                factors={"insider_score": insider_score, "above_sma200": above_200},
            )

        # Weak insider signal — hold
        return Verdict(
            agent=self.codename, ticker=ticker,
            signal=Signal.HOLD, conviction=0.40,
            rationale=f"Marginal insider activity (score={insider_score:.1f}). "
                      f"ALPHA waits for a cleaner signal.",
        )


candidate_alpha = CandidateAlpha()
