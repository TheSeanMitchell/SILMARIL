"""
silmaril.agents.short_alpha — Daily-move short specialist.

The user requested: "an agent specifically designed for short trading that
can capitalize on daily market movements... analyze headlines, social media
posts, and other relevant information to identify minor trades that can
yield significant profits from small investments."

Honest design notes:
  - Retail short-selling has structural disadvantages: short-borrow costs,
    short-squeeze risk, asymmetric loss profile (unbounded upside).
  - The defensible edge is news-driven catalysts on liquid large-caps:
      * Earnings miss with guidance cut
      * FDA rejection / regulatory action
      * Major customer loss / contract termination
      * CFO sudden departure (high specificity historical signal)
      * Credible short report (Hindenburg, Citron, Muddy Waters)
      * Technical breakdown (gap-down on 3x volume below key support)
  - We avoid:
      * Small-cap shorts (squeeze risk)
      * Retail-favorite memestocks (gamma squeeze risk)
      * Names with high short-interest already (crowded short = squeeze fuel)
  - Risk controls:
      * 1-3 day horizon (daily moves, not deep shorts)
      * Hard stop at +3% above entry
      * Position cap 1-2% per name, 5% portfolio max
      * Trade size scales with conviction × news quality
"""
from __future__ import annotations

from .base import Agent, AssetContext, Signal, Verdict


# Negative-catalyst keywords with rough impact weights
NEGATIVE_CATALYSTS = {
    "miss":                    0.35, "missed":                    0.35,
    "guidance cut":            0.55, "lowered guidance":          0.55,
    "withdrew guidance":       0.55, "suspends guidance":         0.55,
    "downgrade":               0.30, "downgraded":                0.30,
    "fraud":                   0.80, "investigation":             0.55,
    "subpoena":                0.55, "sec probe":                 0.60,
    "fda rejection":           0.70, "complete response letter":  0.70,
    "recall":                  0.45, "lawsuit":                   0.30,
    "cfo resigns":             0.50, "cfo departure":             0.50,
    "ceo resigns":             0.45, "stepping down":             0.30,
    "going concern":           0.85, "bankruptcy":                0.95,
    "delisting":               0.85, "restate":                   0.65,
    "cyberattack":             0.40, "data breach":               0.40,
    "short report":            0.50, "hindenburg":                0.55,
    "citron":                  0.45, "muddy waters":              0.50,
    "contract terminated":     0.45, "lost contract":             0.40,
    "plant closure":           0.35, "layoffs":                   0.20,
    "delay":                   0.25, "delayed":                   0.25,
    "warning":                 0.30, "weak quarter":              0.40,
}


# Squeeze-risk filter — these tickers have heightened gamma squeeze potential
SQUEEZE_RISK_BLACKLIST = {
    "GME", "AMC", "BBBY", "BB", "KOSS", "EXPR",
    # Names with chronic high short interest + retail favorability
}


class ShortAlpha(Agent):
    codename = "SHORT_ALPHA"
    specialty = "News-Driven Daily Shorts"
    temperament = (
        "Predatory and disciplined. Hunts catalyst-driven daily moves on "
        "liquid large-caps. Refuses to short illiquid small-caps or "
        "memestocks where squeeze risk is asymmetric. Closes within 1-3 "
        "days regardless of P&L — never married to a thesis."
    )

    # Liquid large-caps only. Conservative starting universe.
    UNIVERSE_TICKERS = {
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD", "INTC",
        "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK",
        "XOM", "CVX", "COP", "OXY",
        "JNJ", "UNH", "PFE", "MRK", "ABBV", "LLY", "BMY", "GILD",
        "WMT", "TGT", "HD", "LOW", "COST", "NKE", "MCD",
        "DIS", "NFLX", "CRM", "ORCL", "ADBE", "CSCO",
        "SPY", "QQQ", "IWM", "DIA",
        "XLF", "XLE", "XLK", "XLV", "XLY", "XLP",
        # Major crypto where shorting via inverse ETFs / Alpaca shortable
        "COIN", "MSTR",
    }

    def _judge(self, ctx: AssetContext) -> Verdict:
        if ctx.ticker in SQUEEZE_RISK_BLACKLIST:
            return Verdict(
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale="Squeeze-risk blacklist — no short on retail-meme names",
            )

        if ctx.ticker not in self.UNIVERSE_TICKERS:
            return Verdict(
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale="Outside SHORT_ALPHA liquid-large-cap universe",
            )

        # ---- 1. Negative catalyst detection ----
        catalyst_score = 0.0
        matched_catalysts = []
        headlines = self._collect_headlines(ctx)
        combined = " ".join(headlines).lower()

        for keyword, weight in NEGATIVE_CATALYSTS.items():
            if keyword in combined:
                catalyst_score += weight
                matched_catalysts.append(keyword)

        catalyst_score = min(1.0, catalyst_score)

        # ---- 2. Sentiment confirmation ----
        sentiment = getattr(ctx, "sentiment_score", 0) or 0
        sentiment_negative = sentiment < -0.20

        # ---- 3. Technical breakdown check ----
        price = ctx.price or 0
        sma_20 = getattr(ctx, "sma_20", None)
        sma_50 = getattr(ctx, "sma_50", None)
        change_pct = getattr(ctx, "change_pct", 0) or 0
        volume = getattr(ctx, "volume", 0) or 0
        avg_vol = getattr(ctx, "avg_volume_30d", 0) or 0

        breakdown = False
        breakdown_reasons = []
        if sma_20 and price < sma_20 * 0.99:
            breakdown_reasons.append("below SMA-20")
            breakdown = True
        if sma_50 and price < sma_50 * 0.98:
            breakdown_reasons.append("below SMA-50")
            breakdown = True
        if change_pct < -2.0 and avg_vol > 0 and volume > avg_vol * 1.5:
            breakdown_reasons.append(f"-{abs(change_pct):.1f}% on {volume/avg_vol:.1f}x volume")
            breakdown = True

        # ---- 4. Decision logic ----
        # STRONG_SELL: catalyst > 0.5 AND (sentiment OR breakdown)
        # SELL:        catalyst > 0.3 AND breakdown, OR catalyst > 0.4 AND sentiment
        # HOLD:        catalyst < 0.3 OR no confirmation
        # ABSTAIN:     no catalyst at all (no signal to act on)

        if catalyst_score == 0 and not breakdown:
            return Verdict(
                signal=Signal.ABSTAIN,
                conviction=0.0,
                rationale="No negative catalyst, no technical breakdown — no setup",
            )

        if catalyst_score >= 0.55 and (sentiment_negative or breakdown):
            conviction = min(0.85, 0.40 + catalyst_score * 0.5)
            rationale = (
                f"STRONG_SELL setup — catalysts: {', '.join(matched_catalysts[:3])}. "
                f"{'Negative sentiment + ' if sentiment_negative else ''}"
                f"{'Technical breakdown: ' + ', '.join(breakdown_reasons[:2]) if breakdown else ''}. "
                f"Target: -3% in 1-3 days. Hard stop at +3%."
            )
            return Verdict(
                signal=Signal.STRONG_SELL,
                conviction=conviction,
                rationale=rationale,
            )

        if (catalyst_score >= 0.30 and breakdown) or \
           (catalyst_score >= 0.40 and sentiment_negative):
            conviction = min(0.65, 0.35 + catalyst_score * 0.3)
            rationale = (
                f"SELL setup — catalysts: {', '.join(matched_catalysts[:3]) or 'none'}. "
                f"{'Sentiment negative. ' if sentiment_negative else ''}"
                f"{'Breakdown: ' + ', '.join(breakdown_reasons[:2]) if breakdown else ''}"
            )
            return Verdict(
                signal=Signal.SELL,
                conviction=conviction,
                rationale=rationale,
            )

        if breakdown and catalyst_score < 0.20:
            return Verdict(
                signal=Signal.HOLD,
                conviction=0.40,
                rationale=(
                    f"Technical breakdown without catalyst confirmation. "
                    f"Wait for headline trigger before entering short."
                ),
            )

        return Verdict(
            signal=Signal.HOLD,
            conviction=0.25,
            rationale=(
                f"Catalyst score {catalyst_score:.2f} but missing confirmation. "
                f"Need sentiment or technical breakdown to short."
            ),
        )

    def _collect_headlines(self, ctx: AssetContext) -> list:
        headlines = []
        # Try multiple field names — backward compat with older AssetContext
        for field_name in ("headlines", "news_headlines", "recent_headlines"):
            v = getattr(ctx, field_name, None)
            if isinstance(v, list):
                headlines.extend(str(h) for h in v if h)
        # Also pull from news items if present
        items = getattr(ctx, "news_items", None)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    h = item.get("headline") or item.get("title") or ""
                    if h:
                        headlines.append(str(h))
        return headlines
