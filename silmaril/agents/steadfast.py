"""
silmaril.agents.steadfast — STEADFAST, the blue-chip patriot.

The agent your grandfather would approve of. Buys only from the
"Crown Jewels" — long-standing American blue chips with dividend
histories and household-name moats. Holds for a minimum of 30 days.
Lectures the rest of the cohort about discipline and patience.

Plays:
  - Dividend payers with 25+ year track records
  - Defensive consumer staples (KO, PG, JNJ, PEP)
  - American institutional brands (DIS, MCD, WMT, HD)
  - Industrials with century-long histories (CAT, MMM, GE, BA)
  - Pharma & healthcare quality (PFE, MRK, JNJ, ABBV)
  - Banks with dividend reliability (JPM, BAC, BRK-B)
  - Energy majors when they yield (XOM, CVX)
  - Telecoms when valuations rationalize (T, VZ)
  - Tobacco when nobody wants it (MO)

Refuses to buy:
  - Anything without a 10+ year dividend history (excl. AAPL grandfathered in)
  - Crypto (obviously)
  - Tech speculative
  - Foreign-listed
  - Biotech without a marketed product

STEADFAST does not get excited. STEADFAST gets paid quarterly.
"""

from __future__ import annotations

from typing import Optional

from .base import Agent, AssetContext, Signal, Verdict


# The "Crown Jewels" — STEADFAST's permitted buy universe.
# Curated to American institutional blue chips with long track records.
CROWN_JEWELS = {
    # Consumer Staples
    "KO":   "Coca-Cola",
    "PEP":  "PepsiCo",
    "PG":   "Procter & Gamble",
    "JNJ":  "Johnson & Johnson",
    "WMT":  "Walmart",
    "COST": "Costco",
    "MO":   "Altria",
    "PM":   "Philip Morris",
    "CL":   "Colgate-Palmolive",
    # Consumer Discretionary
    "MCD":  "McDonald's",
    "DIS":  "Disney",
    "HD":   "Home Depot",
    "LOW":  "Lowe's",
    "NKE":  "Nike",
    "SBUX": "Starbucks",
    # Industrials
    "CAT":  "Caterpillar",
    "MMM":  "3M",
    "GE":   "General Electric",
    "BA":   "Boeing",
    "DE":   "Deere",
    "HON":  "Honeywell",
    "F":    "Ford",
    "GM":   "General Motors",
    # Energy majors (only when yielding)
    "XOM":  "Exxon Mobil",
    "CVX":  "Chevron",
    # Healthcare / Pharma
    "PFE":  "Pfizer",
    "MRK":  "Merck",
    "ABBV": "AbbVie",
    "BMY":  "Bristol-Myers Squibb",
    "LLY":  "Eli Lilly",
    "UNH":  "UnitedHealth",
    # Financials
    "JPM":  "JPMorgan Chase",
    "BAC":  "Bank of America",
    "WFC":  "Wells Fargo",
    "BRK-B": "Berkshire Hathaway",
    "V":    "Visa",
    "MA":   "Mastercard",
    # Telecom
    "T":    "AT&T",
    "VZ":   "Verizon",
    # Utilities
    "DUK":  "Duke Energy",
    "SO":   "Southern Company",
    "NEE":  "NextEra Energy",
    # Grandfathered tech (long enough history for STEADFAST)
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "IBM":  "IBM",
}

MINIMUM_HOLD_DAYS = 30


class Steadfast(Agent):
    codename = "STEADFAST"
    specialty = "American blue-chip dividend payers"
    temperament = "Patient. Skeptical of hype. Quarterly-dividend pace."
    inspiration = "Your grandfather, who bought IBM in 1962 and never sold"
    asset_classes = ("equity",)

    def applies_to(self, ctx: AssetContext) -> bool:
        if not super().applies_to(ctx):
            return False
        return ctx.ticker.upper() in CROWN_JEWELS

    def _judge(self, ctx: AssetContext) -> Verdict:
        ticker = ctx.ticker.upper()
        chg = ctx.change_pct or 0.0
        sent = ctx.sentiment_score or 0.0
        price = ctx.price or 0.0
        sma_200 = getattr(ctx, "sma_200", None)
        rsi = getattr(ctx, "rsi_14", None)

        name = CROWN_JEWELS.get(ticker, ticker)

        # ── STEADFAST's rules ─
        # Buy on dips (below 200-day SMA or RSI < 40), with long-term sentiment OK
        below_sma = sma_200 and price < sma_200 * 0.98
        oversold = rsi and rsi < 40
        very_negative_news = sent < -0.4

        if very_negative_news:
            # Even crown jewels can crack — STEADFAST waits when sentiment is awful
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.HOLD, conviction=0.5,
                rationale=(f"Even {name} can have a bad quarter. Sentiment is "
                           f"sharply negative. STEADFAST waits for the dust to settle "
                           f"rather than catching a falling knife on principle."),
            )

        if (below_sma or oversold) and sent > -0.2:
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.BUY, conviction=0.7,
                rationale=(f"STEADFAST sees value in {name}. Quality compounds. "
                           f"This is what your grandfather would've bought. "
                           f"Hold for the dividend, not for the candle."),
            )

        if chg > 5.0:
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.HOLD, conviction=0.4,
                rationale=(f"{name} ran {chg:+.1f}% today. STEADFAST does not chase. "
                           f"Quality compounds; chasing rarely does."),
            )

        if chg < -3.0 and sent > -0.3:
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.BUY, conviction=0.6,
                rationale=(f"{name} -{abs(chg):.1f}% on no fundamental change. "
                           f"STEADFAST adds to quality on weakness. "
                           f"You buy umbrellas when it rains."),
            )

        if sent > 0.3 and chg > 0.5:
            return Verdict(
                agent=self.codename, ticker=ticker,
                signal=Signal.BUY, conviction=0.55,
                rationale=(f"Constructive backdrop on {name}. STEADFAST initiates "
                           f"or adds. Slow and steady wins the race."),
            )

        return Verdict(
            agent=self.codename, ticker=ticker,
            signal=Signal.HOLD, conviction=0.4,
            rationale=(f"{name} in equilibrium. STEADFAST is patient. "
                       f"He'd rather miss a 5% rally than chase one."),
        )


steadfast = Steadfast()
