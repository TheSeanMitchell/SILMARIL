"""
silmaril.agents.kestrel_plus — The Hurst-Aware Mean Reverter.

The original KESTREL fades RSI extremes. KESTREL_PLUS first measures
whether the underlying time-series is actually mean-reverting before
fading anything. If Hurst exponent < 0.45 → true mean reverter, fade
extremes. If Hurst > 0.55 → trender, stay silent. Between → no signal.

This fixes the trap of fading a strong trend just because RSI > 70.

Computes Hurst via Rescaled Range (R/S) analysis on log returns.
"""
from __future__ import annotations

import math
from typing import List, Optional

from .base import Agent, AssetContext, Signal, Verdict


def _hurst_rs(series: List[float]) -> Optional[float]:
    """Rescaled-range Hurst estimator. Returns None if insufficient data."""
    if not series or len(series) < 64:
        return None

    # Log returns
    rets: List[float] = []
    for i in range(1, len(series)):
        a, b = series[i-1], series[i]
        if a is None or b is None or a <= 0 or b <= 0:
            return None
        rets.append(math.log(b / a))
    if len(rets) < 32:
        return None

    # Geometric chunk sizes from 8 to len/2
    max_chunk = len(rets) // 2
    chunks = []
    s = 8
    while s <= max_chunk:
        chunks.append(s)
        s = int(s * 1.6)
    chunks = sorted(set(chunks))
    if len(chunks) < 3:
        return None

    log_n: List[float] = []
    log_rs: List[float] = []
    for size in chunks:
        groups = len(rets) // size
        if groups == 0:
            continue
        rs_vals = []
        for g in range(groups):
            seg = rets[g*size:(g+1)*size]
            mean = sum(seg) / size
            cum = 0.0
            cum_seq: List[float] = []
            for r in seg:
                cum += r - mean
                cum_seq.append(cum)
            R = max(cum_seq) - min(cum_seq)
            var = sum((r - mean)**2 for r in seg) / size
            S = math.sqrt(var)
            if S > 0:
                rs_vals.append(R / S)
        if rs_vals:
            log_n.append(math.log(size))
            log_rs.append(math.log(sum(rs_vals) / len(rs_vals)))

    if len(log_n) < 3:
        return None

    # OLS slope = Hurst
    nx = len(log_n)
    mx = sum(log_n) / nx
    my = sum(log_rs) / nx
    num = sum((log_n[i] - mx) * (log_rs[i] - my) for i in range(nx))
    den = sum((log_n[i] - mx)**2 for i in range(nx))
    if den == 0:
        return None
    return num / den


class KestrelPlus(Agent):
    codename = "KESTREL+"
    specialty = "Hurst-Aware Mean Reversion"
    temperament = (
        "Smarter than the original KESTREL. Measures whether a series "
        "is actually mean-reverting before fading anything. Stays silent "
        "on trenders. Fades extremes only when the math says fade."
    )
    inspiration = "Kestrel — the falcon that hovers, then dives only on confirmed prey"
    asset_classes = ("equity", "etf", "crypto")

    HURST_REVERTER = 0.45
    HURST_TRENDER = 0.55

    def _judge(self, ctx: AssetContext) -> Verdict:
        ph = ctx.price_history or []
        rsi = ctx.rsi_14

        if len(ph) < 64 or rsi is None:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.HOLD,
                conviction=0.0,
                rationale="insufficient history for Hurst analysis",
            )

        H = _hurst_rs(ph)
        if H is None:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.HOLD,
                conviction=0.0,
                rationale="Hurst undefined",
            )

        factors = {"hurst": round(H, 3), "rsi": round(rsi, 1)}

        # Trender — stay silent
        if H >= self.HURST_TRENDER:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale=f"H={H:.2f} → trender, mean-reversion N/A",
                factors=factors,
            )

        # Ambiguous middle — no edge
        if H >= self.HURST_REVERTER:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.HOLD,
                conviction=0.0,
                rationale=f"H={H:.2f} → no clear regime",
                factors=factors,
            )

        # True mean reverter — fade RSI extremes
        if rsi >= 75:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.SELL,
                conviction=min(0.80, 0.45 + (rsi - 75) * 0.02),
                rationale=f"H={H:.2f} reverter, RSI {rsi:.0f} overbought",
                factors=factors,
            )
        if rsi <= 25:
            return Verdict(
                agent=self.codename,
                ticker=ctx.ticker,
                signal=Signal.BUY,
                conviction=min(0.80, 0.45 + (25 - rsi) * 0.02),
                rationale=f"H={H:.2f} reverter, RSI {rsi:.0f} oversold",
                factors=factors,
            )

        return Verdict(
            agent=self.codename,
            ticker=ctx.ticker,
            signal=Signal.HOLD,
            conviction=0.0,
            rationale=f"H={H:.2f} reverter, RSI {rsi:.0f} not extreme",
            factors=factors,
        )


kestrel_plus = KestrelPlus()
