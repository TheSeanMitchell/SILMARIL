"""KESTREL_PLUS — Hurst-aware mean reversion.

Computes Hurst exponent (R/S) on the price history. Only fades RSI
extremes when H < 0.45 (true mean reverter). Stays silent when H > 0.55
(trender — fading would lose).
"""
from __future__ import annotations

import math
from typing import Optional

from .base import Agent, AssetContext, Verdict, Signal


def _hurst_rs(series, max_chunk=None) -> Optional[float]:
    """Rescaled-range Hurst estimator. Returns None if too short."""
    if not series or len(series) < 64:
        return None
    n = len(series)
    if max_chunk is None:
        max_chunk = n // 2

    # Log returns
    rets = []
    for i in range(1, n):
        a, b = series[i-1], series[i]
        if a is None or b is None or a <= 0 or b <= 0:
            return None
        rets.append(math.log(b / a))
    if len(rets) < 32:
        return None

    chunks = []
    s = 8
    while s <= max_chunk and s <= len(rets):
        chunks.append(s)
        s = int(s * 1.6)
    chunks = sorted(set(chunks))
    if len(chunks) < 3:
        return None

    log_n, log_rs = [], []
    for size in chunks:
        groups = len(rets) // size
        if groups == 0:
            continue
        rs_vals = []
        for g in range(groups):
            seg = rets[g*size:(g+1)*size]
            mean = sum(seg) / size
            cum = 0.0
            cum_seq = []
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
            log_rs.append(math.log(sum(rs_vals)/len(rs_vals)))

    if len(log_n) < 3:
        return None

    # OLS slope = Hurst
    nx = len(log_n)
    mx = sum(log_n) / nx
    my = sum(log_rs) / nx
    num = sum((log_n[i]-mx)*(log_rs[i]-my) for i in range(nx))
    den = sum((log_n[i]-mx)**2 for i in range(nx))
    if den == 0:
        return None
    return num / den


class _KestrelPlusAgent(Agent):
    codename = "KESTREL+"
    bio = (
        "KESTREL+ measures whether a series is actually mean-reverting "
        "before fading it. Hurst < 0.45 → fade extremes. Hurst > 0.55 → "
        "stay quiet, that's a trender. The original KESTREL faded blindly."
    )

    def applies_to(self, ctx: AssetContext) -> bool:
        ph = getattr(ctx, "price_history", None) or []
        rsi = getattr(ctx, "rsi_14", None)
        return len(ph) >= 64 and rsi is not None

    def evaluate(self, ctx: AssetContext) -> Verdict:
        ph = ctx.price_history
        H = _hurst_rs(ph)
        if H is None:
            return Verdict(
                agent=self.codename, signal=Signal.HOLD, conviction=0.0,
                rationale="hurst undefined (too little data)",
            )

        if H >= 0.55:
            return Verdict(
                agent=self.codename, signal=Signal.ABSTAIN, conviction=0.0,
                rationale=f"H={H:.2f} → trender, mean-reversion N/A",
            )
        if H >= 0.45:
            return Verdict(
                agent=self.codename, signal=Signal.HOLD, conviction=0.0,
                rationale=f"H={H:.2f} → no clear regime",
            )

        # H < 0.45 — true mean reverter
        rsi = ctx.rsi_14
        if rsi >= 75:
            return Verdict(
                agent=self.codename, signal=Signal.SELL,
                conviction=min(0.80, 0.45 + (rsi - 75) * 0.02),
                rationale=f"H={H:.2f} mean-revert + RSI {rsi:.0f} overbought",
            )
        if rsi <= 25:
            return Verdict(
                agent=self.codename, signal=Signal.BUY,
                conviction=min(0.80, 0.45 + (25 - rsi) * 0.02),
                rationale=f"H={H:.2f} mean-revert + RSI {rsi:.0f} oversold",
            )

        return Verdict(
            agent=self.codename, signal=Signal.HOLD, conviction=0.0,
            rationale=f"H={H:.2f} mean-revert, but RSI {rsi:.0f} not extreme",
        )


kestrel_plus = _KestrelPlusAgent()
