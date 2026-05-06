"""
silmaril.agents.candidate_gamma — GAMMA, the Macro Regime Reader.

GAMMA reads the economy before it reads the tape.
She uses FRED (Federal Reserve Economic Data) to build a macro picture
and translates it into sector rotation calls.

Signals:
  1. Yield curve slope (10Y - 2Y) — inverted = risk-off
  2. Credit spread (HY - IG) — widening = flight to quality
  3. Leading economic index direction — confirming expansion or contraction
  4. Fed funds rate trajectory — tightening vs easing cycle

GAMMA makes SECTOR calls, not individual stock calls. She votes on:
  ETFs: SPY, QQQ, XLF, XLK, XLE, XLU, XLP, XLI, GLD, TLT, SHV

CANDIDATE — shadow mode. Calls scored, no consensus influence yet.

Data: silmaril.ingestion.fred (FRED API, free key required: FRED_API_KEY)
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict

# GAMMA only speaks on these tickers — sector ETFs + safe havens
GAMMA_UNIVERSE = {
    "SPY", "QQQ", "IWM",                          # broad market
    "XLK", "XLF", "XLE", "XLU", "XLP", "XLI",   # sectors
    "GLD", "SLV", "TLT", "IEF", "SHV", "BIL",   # safe havens + bonds
    "HYG", "LQD",                                  # credit
    "EEM", "EFA",                                  # international
}

try:
    from silmaril.ingestion.fred import get_macro_signals
    _HAS_FRED = True
except Exception:
    _HAS_FRED = False
    def get_macro_signals() -> dict: return {}


class CandidateGamma(Agent):
    codename    = "CANDIDATE_GAMMA"
    specialty   = "FRED macro regime → sector rotation"
    temperament = (
        "Patient. Reads the economy like a poem. "
        "Doesn't trade the news; trades the cycle the news is inside."
    )
    inspiration = "Ray Dalio's economic machine — simplified."
    asset_classes = ("etf",)

    def applies_to(self, ctx: AssetContext) -> bool:
        return ctx.ticker in GAMMA_UNIVERSE

    def _judge(self, ctx: AssetContext) -> Verdict:
        ticker = ctx.ticker
        macro  = get_macro_signals() if _HAS_FRED else {}

        curve_slope    = macro.get("yield_curve_slope", 0.5)   # 10Y-2Y in pct
        credit_spread  = macro.get("credit_spread", 3.0)       # HY-IG in pct
        lei_direction  = macro.get("lei_direction", "flat")     # "up"|"down"|"flat"
        fed_cycle      = macro.get("fed_cycle", "neutral")      # "tightening"|"easing"|"neutral"

        inverted_curve = curve_slope < 0
        wide_spreads   = credit_spread > 4.5
        risk_off       = inverted_curve or wide_spreads
        risk_on        = curve_slope > 0.3 and credit_spread < 3.5 and lei_direction == "up"
        easing         = fed_cycle == "easing"

        # ── Risk-off / defensive rotation ────────────────────────
        if risk_off:
            if ticker in ("GLD", "SLV", "TLT", "IEF", "SHV", "BIL", "XLU", "XLP"):
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.STRONG_BUY, conviction=0.78,
                    rationale=(
                        f"MACRO RISK-OFF: curve={curve_slope:+.2f}% spread={credit_spread:.1f}%. "
                        f"{ticker} is a defensive safe-haven. GAMMA rotates here."
                    ),
                    factors={"curve_slope": curve_slope, "credit_spread": credit_spread,
                             "risk_off": True},
                )
            if ticker in ("SPY", "QQQ", "XLK", "IWM", "HYG", "EEM"):
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.SELL, conviction=0.65,
                    rationale=(
                        f"MACRO RISK-OFF: rotating out of risk assets. "
                        f"Yield curve {curve_slope:+.2f}%, credit spread {credit_spread:.1f}%."
                    ),
                )

        # ── Risk-on / growth rotation ─────────────────────────────
        if risk_on:
            if ticker in ("XLK", "QQQ", "XLF", "XLI", "EEM"):
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.BUY, conviction=0.70,
                    rationale=(
                        f"MACRO RISK-ON: curve={curve_slope:+.2f}% LEI={lei_direction}. "
                        f"{ticker} benefits from expansion phase. GAMMA is long growth."
                    ),
                    factors={"curve_slope": curve_slope, "lei_direction": lei_direction},
                )
            if ticker in ("GLD", "TLT", "SHV", "BIL"):
                return Verdict(
                    agent=self.codename, ticker=ticker,
                    signal=Signal.SELL, conviction=0.55,
                    rationale=f"Risk-on rotation — out of defensive haven {ticker}.",
                )

        # ── Fed easing: bonds and rate-sensitive sectors ──────────
        if easing and ticker in ("TLT", "IEF", "XLU", "XLF"):
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.BUY, conviction=0.60,
                rationale=f"Fed easing cycle benefits rate-sensitive {ticker}.",
            )

        return Verdict(
            agent=self.codename, ticker=ticker,
            signal=Signal.HOLD, conviction=0.38,
            rationale=f"No clear macro regime signal for {ticker}. GAMMA holds.",
        )


candidate_gamma = CandidateGamma()
