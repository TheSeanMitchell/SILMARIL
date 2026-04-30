"""
silmaril.agents.contrarian — Crowded-Trade Fade Detector.

CONTRARIAN exists because everyone using the same indicators creates
predictable behavior at trigger points. When RSI hits 70 and ten million
retail traders all sell, the market often bounces. CONTRARIAN looks for
exactly those crowded-positioning extremes and fades them.

Decision logic:
  1. Compute "crowdedness score" — how aligned are positioning + sentiment
  2. If crowdedness > 0.60 AND price has moved with the crowd, fade it
  3. If crowdedness < 0.40, ABSTAIN (no edge in non-extreme conditions)
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


class Contrarian(Agent):
    codename = "CONTRARIAN"
    specialty = "Crowded-Trade Fade"
    temperament = (
        "Cynical and contrarian. Reads what everyone else is doing and "
        "bets against the consensus when the crowd is most aligned. "
        "Lives by the rule: 'When everyone leans one way, the boat tips.'"
    )

    UNIVERSE_TICKERS = {
        # Large-cap equities only — crowded-fade needs liquidity
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
        "JPM", "BAC", "WFC", "GS", "MS",
        "XOM", "CVX", "COP",
        "JNJ", "UNH", "PFE",
        "SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK",
        "BTC-USD", "ETH-USD", "SOL-USD",
    }

    def _judge(self, ctx: AssetContext) -> Verdict:
        if ctx.ticker not in self.UNIVERSE_TICKERS:
            return Verdict(
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale="Outside CONTRARIAN universe (large-cap liquid only)",
            )

        crowded_score = 0.0
        crowded_dir = 0
        signals_used = 0
        reasons = []

        # 1. RSI extreme
        rsi = getattr(ctx, "rsi", None)
        if rsi is not None:
            if rsi > 75:
                crowded_score += 0.35
                crowded_dir += 1
                signals_used += 1
                reasons.append(f"RSI {rsi:.0f} (overbought)")
            elif rsi < 25:
                crowded_score += 0.35
                crowded_dir -= 1
                signals_used += 1
                reasons.append(f"RSI {rsi:.0f} (oversold)")

        # 2. Sentiment extreme
        sentiment = getattr(ctx, "sentiment_score", None)
        if sentiment is not None:
            if sentiment > 0.6:
                crowded_score += 0.25
                crowded_dir += 1
                signals_used += 1
                reasons.append(f"sentiment +{sentiment:.2f} (euphoric)")
            elif sentiment < -0.4:
                crowded_score += 0.25
                crowded_dir -= 1
                signals_used += 1
                reasons.append(f"sentiment {sentiment:.2f} (despair)")

        # 3. Put/call ratio
        pc_ratio = getattr(ctx, "put_call_ratio", None)
        if pc_ratio is not None:
            if pc_ratio < 0.6:
                crowded_score += 0.20
                crowded_dir += 1
                signals_used += 1
                reasons.append(f"P/C {pc_ratio:.2f} (call-heavy)")
            elif pc_ratio > 1.3:
                crowded_score += 0.20
                crowded_dir -= 1
                signals_used += 1
                reasons.append(f"P/C {pc_ratio:.2f} (put-heavy)")

        # 4. Recent stretch from SMA-20
        change_pct = getattr(ctx, "change_pct", 0) or 0
        sma_20 = getattr(ctx, "sma_20", None)
        if sma_20 and ctx.price:
            stretched = (ctx.price - sma_20) / sma_20
            if abs(stretched) > 0.05:
                crowded_score += 0.20
                crowded_dir += 1 if stretched > 0 else -1
                signals_used += 1
                reasons.append(f"price {stretched*100:+.1f}% from SMA-20")

        if signals_used < 2:
            return Verdict(
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale=f"Insufficient crowdedness signals ({signals_used}/2 minimum)",
            )

        if crowded_score >= 0.55 and crowded_dir > 0:
            return Verdict(
                signal=Signal.SELL,
                conviction=min(0.75, crowded_score),
                rationale=(
                    f"Crowded LONG fade — score {crowded_score:.2f} "
                    f"({signals_used} signals: {', '.join(reasons)}). "
                    f"Crowd is leaning long; pullback probable."
                ),
            )
        elif crowded_score >= 0.55 and crowded_dir < 0:
            return Verdict(
                signal=Signal.BUY,
                conviction=min(0.75, crowded_score),
                rationale=(
                    f"Crowded SHORT fade — score {crowded_score:.2f} "
                    f"({signals_used} signals: {', '.join(reasons)}). "
                    f"Oversold extremes typically bounce."
                ),
            )
        else:
            return Verdict(
                signal=Signal.HOLD,
                conviction=0.30,
                rationale=f"Crowdedness {crowded_score:.2f} below 0.55 threshold",
            )
