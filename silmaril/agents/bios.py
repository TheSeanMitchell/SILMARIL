"""
silmaril.agents.bios — Rich biographical profiles for every agent.

These bios are the long-form explanation of each agent's:
  • Trading style and strategy
  • Temperament and personality
  • Universe of what they'll evaluate
  • Strengths and failure modes
  • How to read their votes

Surfaced in the agent roster drawer on the dashboard. Keeping them in
one file rather than on each agent class makes them easy to edit and
keeps the agent files focused on logic.
"""

from __future__ import annotations

from typing import Dict


BIOS: Dict[str, Dict[str, str]] = {

    "AEGIS": {
        "title": "The Capital Shield",
        "strategy": (
            "Defensive overlay. AEGIS evaluates regime, volatility, and "
            "drawdown risk rather than chasing specific setups. Its votes "
            "are almost always HOLD or SELL. Its purpose is not to find "
            "opportunity — it's to preserve capital during dangerous regimes."
        ),
        "style": (
            "Cautious, methodical, conservative. Reads VIX, trend breaks, "
            "and correlation clusters. Rarely excited, never panicked."
        ),
        "personality": (
            "The voice that pulls you back from the cliff. Unpopular when "
            "markets trend up, essential when they break."
        ),
        "universe": "Every asset. Always votes.",
        "strength": "Keeping the book alive through bear markets and vol spikes.",
        "failure_mode": (
            "Misses early stages of powerful rallies by staying defensive. "
            "Accept that; the insurance is worth the premium."
        ),
        "power": "VETO — can downgrade any bullish consensus when its defensive conviction is high.",
    },

    "FORGE": {
        "title": "The Builder of Trends",
        "strategy": (
            "Momentum-following tech specialist. FORGE looks for clean "
            "uptrends in tech and growth names — price above SMA-20 above "
            "SMA-50, constructive RSI, supportive sentiment. Buys strength."
        ),
        "style": "Aggressive but systematic. Favors names with durable trend structure.",
        "personality": "Optimistic, builder-archetype — sees a working system and wants to own it.",
        "universe": "Equities and tech-heavy ETFs (XLK, SMH, IGV, QQQ, ARKK).",
        "strength": "Catches and rides powerful secular moves in tech.",
        "failure_mode": "Late to exit when trends break. Pairs well with AEGIS's caution.",
    },

    "THUNDERHEAD": {
        "title": "The Storm",
        "strategy": (
            "Volatility-expansion breakout specialist. Requires price to "
            "break its 20-day range on 1.4×+ average volume. Otherwise "
            "abstains completely — no breakout, no opinion."
        ),
        "style": "Binary. Either absent or maximally committed. No half-measures.",
        "personality": "Loud, confident, occasionally spectacularly wrong.",
        "universe": "Equities, ETFs, crypto — anywhere volatility expansion happens.",
        "strength": "Catches the first 20% of powerful breakouts.",
        "failure_mode": "Fake-outs on low-conviction breaks; stops get run.",
    },

    "JADE": {
        "title": "The Rage-Buyer",
        "strategy": (
            "Deep oversold reversion. Waits for RSI under 30 at major "
            "support (near SMA-200) combined with negative sentiment — "
            "capitulation conditions. Only takes long trades, never shorts."
        ),
        "style": "Contrarian, silent most days, decisive in panic.",
        "personality": (
            "Hulk-archetype. Rare outbursts, but when he moves, he moves "
            "with everything he has."
        ),
        "universe": "Equities and broad ETFs.",
        "strength": "Catches capitulation bottoms other agents refuse to touch.",
        "failure_mode": "Occasionally buys a falling knife — but with 1.5 ATR stops.",
    },

    "VEIL": {
        "title": "The Hidden Watcher",
        "strategy": (
            "Sentiment–price divergence. Looks for situations where price "
            "and news sentiment disagree — a crowd turning negative on a "
            "stock that keeps rising (sell signal) or warming on a stock "
            "that keeps falling (buy signal)."
        ),
        "style": "Subtle, patient, data-driven. Needs ≥4 articles for a valid read.",
        "personality": (
            "Reads the room. Trades on what the crowd feels but the tape "
            "has not yet priced."
        ),
        "universe": "Equities and sector ETFs with meaningful news flow.",
        "strength": "Catches turns before they show up on charts.",
        "failure_mode": "Blind on low-news tickers. Thin sentiment samples are noise.",
    },

    "KESTREL": {
        "title": "The Patient Hunter",
        "strategy": (
            "Coiled Bollinger bands plus directional trigger. Abstains most "
            "days. When the bands compress (width < 6%) AND the trend is "
            "clean, takes tight-stop entries with 3:1 reward-to-risk."
        ),
        "style": "Precision over volume. Takes maybe one setup a week per ticker.",
        "personality": "Patient, quiet, lethal when opportunity aligns.",
        "universe": "Equities and liquid ETFs.",
        "strength": "Best reward-to-risk of any agent by design.",
        "failure_mode": "Misses moves that never compress — pure breakouts.",
    },

    "OBSIDIAN": {
        "title": "The Resource King",
        "strategy": (
            "Commodities and resource-equity specialist. Evaluates only "
            "energy, materials, precious metals, and commodity ETFs. "
            "Bias toward uptrending hard assets with constructive sentiment."
        ),
        "style": "Patient hoarder. Plays inflation, scarcity, sovereign flows.",
        "personality": "Ancient wealth. Believes in things you can hold.",
        "universe": "XLE, XLB, GLD, SLV, USO, UNG, DBC, CPER, XOM, CVX, FCX, NEM, GOLD.",
        "strength": "Only agent with meaningful opinions on hard assets.",
        "failure_mode": "Silent during long risk-on regimes when commodities underperform.",
    },

    "ZENITH": {
        "title": "The Long Rider",
        "strategy": (
            "Multi-timeframe trend follower. Requires perfect SMA stack "
            "(price > 20 > 50 > 200) and rides positions with wide 3-ATR "
            "stops. Won't exit on minor pullbacks."
        ),
        "style": "High altitude, long horizon. Ignores daily noise.",
        "personality": "Cosmic patience. Thinks in months, not days.",
        "universe": "Equities, ETFs, crypto.",
        "strength": "Captures the full body of secular moves.",
        "failure_mode": "Gives back significant open profits during corrections.",
    },

    "WEAVER": {
        "title": "The Micro Scalper",
        "strategy": (
            "Short-horizon RSI reversals and SMA-20 pullbacks in uptrends. "
            "Tight 1.5 ATR stops, 2.5 ATR targets. Takes many small wins."
        ),
        "style": "Fast, nimble, high activity.",
        "personality": "Hyperactive. Would rather be wrong quickly than right slowly.",
        "universe": "Equities and liquid ETFs.",
        "strength": "Produces regular, bounded-risk opportunities in any regime.",
        "failure_mode": "Whipsaws in choppy, directionless markets.",
    },

    "HEX": {
        "title": "The Probabilist",
        "strategy": (
            "Statistical mean-reversion. Trades prices more than 2 standard "
            "deviations from their 20-day mean, expecting reversion. Size "
            "scales with how extreme the deviation is."
        ),
        "style": "Cold-blooded, mathematical. No narrative — just numbers.",
        "personality": "Reads probability like a second language.",
        "universe": "Equities, ETFs, crypto.",
        "strength": "Profitable in consolidations and range-bound markets.",
        "failure_mode": "Fights the tape during strong trends — loses to ZENITH/FORGE there.",
    },

    "SYNTH": {
        "title": "The Synthesist",
        "strategy": (
            "Cross-market regime and rotation. Watches bonds, dollar, gold, "
            "equities together. Favors defensives in risk-off regimes, "
            "cyclicals in risk-on."
        ),
        "style": "Macro lens. Evaluates the whole chessboard, not one square.",
        "personality": "Synthetic perception across systems. Sees the pattern others miss.",
        "universe": "Sector ETFs and indices primarily.",
        "strength": "Adds strong regime-aware bias to the debate.",
        "failure_mode": "Can be early on rotations — macro plays unfold in weeks.",
    },

    "SPECK": {
        "title": "The Small Thing",
        "strategy": (
            "Small-cap and overlooked. Actively avoids mega-caps. Looks "
            "for low-coverage tickers with positive sentiment and price "
            "above SMA-50 — small edges before the crowd arrives."
        ),
        "style": "Under the radar. Small scale, outsized leverage.",
        "personality": "Ant-Man archetype. Size is an advantage when you're small.",
        "universe": "IWM, ARKK, non-mega-cap equities.",
        "strength": "Finds overlooked setups big agents won't touch.",
        "failure_mode": "Low-coverage names are illiquid; execution slippage matters.",
    },

    "VESPA": {
        "title": "The Catalyst Striker",
        "strategy": (
            "Event-driven. Takes directional bets into earnings (within "
            "5 days) when sentiment is one-sided, and trades declared "
            "event flags (FDA, FOMC, deal close)."
        ),
        "style": "Fast in, fast out. Exits around the catalyst, not after.",
        "personality": "Opportunistic, tactical, short attention span.",
        "universe": "Equities with known catalysts.",
        "strength": "Captures positioning into known events before the market prices them.",
        "failure_mode": "Vulnerable to event-outcome surprise — binary risk.",
    },

    "MAGUS": {
        "title": "The Time Reader",
        "strategy": (
            "Seasonality and calendar effects. Plays Santa Rally, sell-in-"
            "May, turn-of-month, Friday drift on the major indices."
        ),
        "style": "Cyclical, rhythm-based. Small individual edges, accumulates.",
        "personality": "Doctor Strange archetype — reading the timelines.",
        "universe": "SPY, QQQ, DIA, IWM, VTI only.",
        "strength": "Non-correlated edge — works in any regime.",
        "failure_mode": "Seasonal effects erode as they become widely known.",
    },

    "TALON": {
        "title": "The Aerial View",
        "strategy": (
            "Market structure on the indices themselves. Evaluates SPY, "
            "QQQ, DIA, IWM, VTI based on SMA stack and VIX context."
        ),
        "style": "Top-down, macro-structural. Doesn't care about individual names.",
        "personality": "Falcon archetype — sees the whole board from altitude.",
        "universe": "Broad indices only.",
        "strength": "Clean structural read on the market itself.",
        "failure_mode": "Silent on anything outside the index ETFs.",
    },

    "SCROOGE": {
        "title": "The $1 Compounder",
        "strategy": (
            "Takes whatever SCROOGE has (starts at $1) and buys the single "
            "highest-consensus pick every day. Sells next day, rolls into "
            "the next. Full conviction, every day, forever. When he dies "
            "(balance under $0.05), he is reborn at $1."
        ),
        "style": "Zero diversification. Zero risk management. Pure compounding ceremony.",
        "personality": "Parsimonious, patient, brutally compounded.",
        "universe": "Whatever the team ranks highest — any asset class.",
        "strength": "Demonstrates the raw output of the consensus system.",
        "failure_mode": "When consensus is wrong, SCROOGE loses everything and resets.",
    },

    "MIDAS": {
        "title": "The Hard-Currency Sovereign",
        "strategy": (
            "Parallel compounder to SCROOGE, restricted to hard currencies "
            "and precious metals only. Gold, silver, platinum, palladium, "
            "USD, EUR, JPY, CHF. Rotates only among these. Refuses to "
            "touch stocks or crypto."
        ),
        "style": "Ancient, patient, sovereign. Wealth that outlasts empires.",
        "personality": "King Midas — slow accumulation of things that have always been wealth.",
        "universe": "GLD, IAU, SLV, SIVR, PPLT, PALL, UUP, FXE, FXY, FXF.",
        "strength": "Uncorrelated to SCROOGE. Survives regimes that break equities.",
        "failure_mode": "Misses multi-year equity bull markets entirely.",
    },
}


def get_bio(codename: str) -> Dict[str, str]:
    """Return the full bio dict for an agent, or a default skeleton."""
    return BIOS.get(codename, {
        "title": codename,
        "strategy": "No extended bio available.",
        "style": "",
        "personality": "",
        "universe": "",
        "strength": "",
        "failure_mode": "",
    })
