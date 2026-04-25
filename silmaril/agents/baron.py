"""
silmaril.agents.baron — The Baron, oil-energy specialist.

Plays the oil complex like a real oil baron would:
  - Long crude via USO/BNO/UCO when fundamentals + sentiment align
  - Short crude via SCO/DRIP when macro deteriorates
  - Refinery plays (VLO/PSX/MPC) when crack spreads widen
  - Integrated majors (XOM/CVX) for dividend + duration
  - E&P pure-plays (OXY/EOG/PXD) for upside leverage
  - Services (SLB/HAL/BKR) for capex cycle
  - Natural gas (UNG/BOIL/KOLD) for asymmetric weather plays

Watches:
  - WTI vs Brent spread (geopolitical signal)
  - Front-month vs back-month (contango / backwardation)
  - EIA crude inventory (Wed 10:30 AM ET) — overrides other signals on report day
  - OPEC announcements (sentiment keyword detection)
  - Crack spreads (refining margins) — drives refiner positioning

The Baron is patient. He'll sit in cash for weeks waiting for asymmetric
opportunity. When he moves, he moves with conviction, both long and short.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .base import Agent, AssetContext, Signal, Verdict
from ..execution.detail import build_execution


BARON_UNIVERSE: Dict[str, str] = {
    # Crude oil long
    "USO":   "United States Oil Fund (WTI)",
    "BNO":   "United States Brent Oil Fund",
    "UCO":   "ProShares Ultra Bloomberg Crude (2× long)",
    # Crude oil short / inverse
    "SCO":   "ProShares UltraShort Bloomberg Crude (2× short)",
    "DRIP": "Direxion Daily S&P Oil & Gas E&P Bear (3× short)",
    # Natural gas
    "UNG":   "United States Natural Gas Fund",
    "BOIL":  "ProShares Ultra Bloomberg Natural Gas (2× long)",
    "KOLD":  "ProShares UltraShort Bloomberg Natural Gas (2× short)",
    # Sector ETFs
    "XLE":   "Energy Select Sector SPDR",
    "XOP":   "SPDR S&P Oil & Gas Exploration & Production",
    "OIH":   "VanEck Oil Services ETF",
    "GUSH":  "Direxion Daily S&P Oil & Gas E&P Bull (2× long)",
    # Integrated majors
    "XOM":   "Exxon Mobil",
    "CVX":   "Chevron",
    "COP":   "ConocoPhillips",
    "SHEL":  "Shell",
    "BP":    "BP",
    # E&P pure plays
    "OXY":   "Occidental Petroleum",
    "EOG":   "EOG Resources",
    "PXD":   "Pioneer Natural Resources",
    "DVN":   "Devon Energy",
    "FANG":  "Diamondback Energy",
    # Services
    "SLB":   "Schlumberger",
    "HAL":   "Halliburton",
    "BKR":   "Baker Hughes",
    # Refiners
    "VLO":   "Valero Energy",
    "PSX":   "Phillips 66",
    "MPC":   "Marathon Petroleum",
}

# Tickers where SHORT inverse signal makes sense (BUY of the inverse = bearish view)
SHORT_INSTRUMENTS = {"SCO", "DRIP", "KOLD"}
LONG_LEVERAGED = {"UCO", "GUSH", "BOIL"}


class Baron(Agent):
    codename = "BARON"
    specialty = "Oil & energy complex"
    temperament = "Patient. Asymmetric. Plays both directions."
    inspiration = "John D. Rockefeller crossed with a Texas wildcatter"
    asset_classes = ("equity", "etf")

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker.upper() in BARON_UNIVERSE

    def _judge(self, ctx: AssetContext) -> Verdict:
        ticker = ctx.ticker.upper()
        chg = ctx.change_pct or 0.0
        sent = ctx.sentiment_score or 0.0
        articles = ctx.article_count or 0

        # Check sentiment keywords from headlines if available
        opec_signal = self._detect_opec_signal(ctx)
        eia_signal = self._detect_eia_signal(ctx)

        # ── Inverse instruments ─ a BUY here means "I'm bearish on oil" ─
        if ticker in SHORT_INSTRUMENTS:
            # Buy inverse only on clear macro deterioration
            if sent < -0.3 and chg > 1.5 and articles >= 3:
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.BUY, conviction=0.6,
                    rationale=(f"Bearish oil thesis. Negative sentiment ({sent:+.2f}) "
                               f"with {ticker} catching bid. Baron hedges via inverse."),
                )
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.HOLD, conviction=0.3,
                rationale="Inverse oil instruments only justified on confirmed macro break.",
            )

        # ── Leveraged longs: only on STRONG conviction ─
        if ticker in LONG_LEVERAGED:
            if sent > 0.3 and chg > 2.0 and (opec_signal == "bullish" or eia_signal == "bullish"):
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.STRONG_BUY, conviction=0.75,
                    rationale=(f"2× leveraged long. {ticker} momentum {chg:+.1f}% "
                               f"with {opec_signal or eia_signal} catalyst. Baron presses."),
                )
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.HOLD, conviction=0.4,
                rationale="Leveraged products require near-perfect setup. Baron waits.",
            )

        # ── Refiners — driven by crack spreads (proxied by sentiment + price action) ─
        if ticker in {"VLO", "PSX", "MPC"}:
            if sent > 0.15 and chg > 0.5:
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.BUY, conviction=0.65,
                    rationale=(f"Refiner setup. {ticker} catches a bid with constructive "
                               f"sentiment. Baron likes refining margin expansion."),
                )
            if sent < -0.2 and chg < -1.0:
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.SELL, conviction=0.55,
                    rationale=(f"{ticker} breaking down on negative sentiment. "
                               f"Crack spreads likely compressing."),
                )
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.HOLD, conviction=0.35,
                rationale="Refiner in equilibrium. Baron prefers patience.",
            )

        # ── Integrated majors: dividend + duration. Baron loves them on dips. ─
        if ticker in {"XOM", "CVX", "COP", "SHEL", "BP"}:
            if chg < -1.5 and sent > -0.1:
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.BUY, conviction=0.7,
                    rationale=(f"{ticker} on a dip ({chg:+.1f}%) without sentiment "
                               f"breakdown. Baron buys the integrated major's dividend."),
                )
            if chg > 3.0:
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.HOLD, conviction=0.4,
                    rationale="Integrated major running hot. Baron doesn't chase quality at premiums.",
                )
            if sent > 0.2:
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.BUY, conviction=0.55,
                    rationale=f"Constructive sentiment on {ticker}. Baron accumulates the dividend.",
                )
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.HOLD, conviction=0.4,
                rationale="Integrated major. Baron holds for the dividend.",
            )

        # ── E&P pure plays: high beta to crude. ─
        if ticker in {"OXY", "EOG", "PXD", "DVN", "FANG"}:
            if eia_signal == "bullish" or (sent > 0.25 and chg > 1.0):
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.BUY, conviction=0.65,
                    rationale=(f"E&P with crude tailwind. {ticker} {chg:+.1f}% "
                               f"with bullish backdrop. Baron takes the leverage."),
                )
            if sent < -0.3:
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.SELL, conviction=0.55,
                    rationale=f"E&P {ticker} on negative sentiment. Baron de-risks the leveraged play.",
                )
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.HOLD, conviction=0.35,
                rationale=f"{ticker} awaits a clear macro impulse.",
            )

        # ── Services: capex-cycle plays ─
        if ticker in {"SLB", "HAL", "BKR"}:
            if sent > 0.2 and chg > 0.5:
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.BUY, conviction=0.6,
                    rationale=(f"Oil services on a positive capex signal. {ticker} "
                               f"benefits from upstream activity."),
                )
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.HOLD, conviction=0.4,
                rationale="Services trade on the capex cycle — no clear signal today.",
            )

        # ── USO / BNO / UNG / sector ETFs ─
        if ticker in {"USO", "BNO", "UNG", "XLE", "XOP", "OIH"}:
            if eia_signal == "bullish" and sent > 0.1:
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.STRONG_BUY, conviction=0.7,
                    rationale=(f"EIA inventory tailwind + constructive sentiment. "
                               f"Baron presses {ticker}."),
                )
            if eia_signal == "bearish":
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.SELL, conviction=0.6,
                    rationale=f"EIA inventory build is bearish for {ticker}. Baron exits.",
                )
            if chg > 2.0 and sent > 0.2:
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.BUY, conviction=0.6,
                    rationale=f"{ticker} momentum with sentiment confirmation.",
                )
            if chg < -2.0 and sent < -0.1:
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.SELL, conviction=0.5,
                    rationale=f"{ticker} breaking down with bearish flow.",
                )
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.HOLD, conviction=0.4,
                rationale=f"{ticker} in chop. Baron waits for asymmetric setup.",
            )

        return Verdict(
            agent=self.codename, ticker=ticker,
            signal=Signal.HOLD, conviction=0.3,
            rationale="No clear oil-baron thesis on this name today.",
        )

    @staticmethod
    def _detect_opec_signal(ctx: AssetContext) -> Optional[str]:
        """Scan headlines for OPEC+ signals."""
        headlines = getattr(ctx, "recent_headlines", []) or []
        text = " ".join(h.get("title", "").lower() for h in headlines if isinstance(h, dict))
        if not text:
            return None
        if any(w in text for w in ["opec cut", "production cut", "supply cut", "extend cuts"]):
            return "bullish"
        if any(w in text for w in ["opec increase", "production increase", "supply boost", "raise output"]):
            return "bearish"
        return None

    @staticmethod
    def _detect_eia_signal(ctx: AssetContext) -> Optional[str]:
        """Scan headlines for EIA inventory signals."""
        headlines = getattr(ctx, "recent_headlines", []) or []
        text = " ".join(h.get("title", "").lower() for h in headlines if isinstance(h, dict))
        if not text:
            return None
        if any(w in text for w in ["draw", "drawdown", "stockpile decline", "inventory drop"]):
            return "bullish"
        if any(w in text for w in ["build", "inventory rise", "stockpile surge", "supply glut"]):
            return "bearish"
        return None


baron = Baron()
