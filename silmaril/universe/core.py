"""
silmaril.universe.core — The permanent universe of tracked assets.

These ~100 tickers are tracked on every run. They span the major asset
classes so the full team of agents has something to evaluate. Discovered
tickers (from news ingestion) are tracked separately for 7 days before
either graduating into this list or aging out.

Adding a ticker: just append it to the right category.
Removing: delete the line. No other changes required.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Tuple


# ─────────────────────────────────────────────────────────────────
# Universe definition
# Each entry: (ticker, display_name, sector)
# ─────────────────────────────────────────────────────────────────

INDICES: List[Tuple[str, str, str]] = [
    ("SPY",  "SPDR S&P 500 ETF",                    "Index"),
    ("QQQ",  "Invesco QQQ (Nasdaq-100)",            "Index"),
    ("DIA",  "SPDR Dow Jones Industrial Average",   "Index"),
    ("IWM",  "iShares Russell 2000 (Small Cap)",    "Index"),
    ("VTI",  "Vanguard Total Stock Market",         "Index"),
    ("EFA",  "iShares MSCI EAFE (Developed ex-US)", "Index"),
    ("EEM",  "iShares MSCI Emerging Markets",       "Index"),
]

SECTOR_ETFS: List[Tuple[str, str, str]] = [
    ("XLK",  "Technology Select Sector SPDR",       "Technology"),
    ("XLF",  "Financial Select Sector SPDR",        "Financials"),
    ("XLE",  "Energy Select Sector SPDR",           "Energy"),
    ("XLV",  "Health Care Select Sector SPDR",      "Healthcare"),
    ("XLI",  "Industrial Select Sector SPDR",       "Industrials"),
    ("XLP",  "Consumer Staples Select Sector SPDR", "Staples"),
    ("XLY",  "Consumer Discretionary Select SPDR",  "Discretionary"),
    ("XLU",  "Utilities Select Sector SPDR",        "Utilities"),
    ("XLB",  "Materials Select Sector SPDR",        "Materials"),
    ("XLRE", "Real Estate Select Sector SPDR",      "Real Estate"),
    ("XLC",  "Communication Services Select SPDR",  "Communications"),
    ("SMH",  "VanEck Semiconductor ETF",            "Semiconductors"),
    ("SOXX", "iShares Semiconductor ETF",           "Semiconductors"),
    ("IGV",  "iShares Software ETF",                "Software"),
    ("ARKK", "ARK Innovation ETF",                  "Innovation"),
]

MEGA_CAPS: List[Tuple[str, str, str]] = [
    ("AAPL",  "Apple Inc.",                 "Technology"),
    ("MSFT",  "Microsoft Corporation",      "Technology"),
    ("GOOGL", "Alphabet Inc. Class A",      "Technology"),
    ("AMZN",  "Amazon.com Inc.",            "Discretionary"),
    ("META",  "Meta Platforms Inc.",        "Communications"),
    ("NVDA",  "NVIDIA Corporation",         "Technology"),
    ("TSLA",  "Tesla Inc.",                 "Discretionary"),
    ("BRK-B", "Berkshire Hathaway B",       "Financials"),
    ("JPM",   "JPMorgan Chase & Co.",       "Financials"),
    ("V",     "Visa Inc.",                  "Financials"),
    ("MA",    "Mastercard Incorporated",    "Financials"),
    ("JNJ",   "Johnson & Johnson",          "Healthcare"),
    ("UNH",   "UnitedHealth Group",         "Healthcare"),
    ("LLY",   "Eli Lilly and Company",      "Healthcare"),
    ("XOM",   "Exxon Mobil Corporation",    "Energy"),
    ("CVX",   "Chevron Corporation",        "Energy"),
    ("HD",    "The Home Depot Inc.",        "Discretionary"),
    ("PG",    "The Procter & Gamble Co.",   "Staples"),
    ("KO",    "The Coca-Cola Company",      "Staples"),
    ("WMT",   "Walmart Inc.",               "Staples"),
    ("COST",  "Costco Wholesale",           "Staples"),
    ("SPCX",  "SpaceX (Space Exploration)", "Technology"),  # IPO debut 2026-06-12 — auto-activates via PENDING_LISTINGS
]

TECH_GROWTH: List[Tuple[str, str, str]] = [
    ("AMD",   "Advanced Micro Devices",     "Semiconductors"),
    ("AVGO",  "Broadcom Inc.",              "Semiconductors"),
    ("QCOM",  "QUALCOMM Incorporated",      "Semiconductors"),
    ("INTC",  "Intel Corporation",          "Semiconductors"),
    ("TSM",   "Taiwan Semiconductor",       "Semiconductors"),
    ("ASML",  "ASML Holding N.V.",          "Semiconductors"),
    ("MU",    "Micron Technology",          "Semiconductors"),
    ("ORCL",  "Oracle Corporation",         "Software"),
    ("CRM",   "Salesforce Inc.",            "Software"),
    ("ADBE",  "Adobe Inc.",                 "Software"),
    ("NOW",   "ServiceNow Inc.",            "Software"),
    ("PLTR",  "Palantir Technologies",      "Software"),
    ("SNOW",  "Snowflake Inc.",             "Software"),
    ("NFLX",  "Netflix Inc.",               "Communications"),
    ("DIS",   "The Walt Disney Company",    "Communications"),
    ("UBER",  "Uber Technologies",          "Technology"),
    ("SHOP",  "Shopify Inc.",               "Technology"),
    ("PANW",  "Palo Alto Networks",         "Software"),
    ("CRWD",  "CrowdStrike Holdings",       "Software"),
]

CRYPTO: List[Tuple[str, str, str]] = [
    ("BTC-USD", "Bitcoin",                  "Crypto"),
    ("ETH-USD", "Ethereum",                 "Crypto"),
    ("SOL-USD", "Solana",                   "Crypto"),
]

COMMODITIES: List[Tuple[str, str, str]] = [
    ("GLD",  "SPDR Gold Shares",            "Commodities"),
    ("SLV",  "iShares Silver Trust",        "Commodities"),
    ("USO",  "United States Oil Fund",      "Commodities"),
    ("UNG",  "United States Natural Gas",   "Commodities"),
    ("DBC",  "Invesco DB Commodity Index",  "Commodities"),
    ("CPER", "United States Copper Index",  "Commodities"),
]

BONDS_RATES: List[Tuple[str, str, str]] = [
    ("TLT",  "iShares 20+ Year Treasury",   "Rates"),
    ("IEF",  "iShares 7-10 Year Treasury",  "Rates"),
    ("SHY",  "iShares 1-3 Year Treasury",   "Rates"),
    ("HYG",  "iShares High Yield Corporate", "Credit"),
    ("LQD",  "iShares Investment Grade",    "Credit"),
]

FX_MACRO: List[Tuple[str, str, str]] = [
    ("UUP",  "Invesco DB US Dollar Index",  "FX"),
    ("FXE",  "Invesco CurrencyShares Euro", "FX"),
    ("FXY",  "Invesco CurrencyShares Yen",  "FX"),
]

# VIX is fetched specially for the regime classifier — separate from the
# voting universe.
VOLATILITY_PROXY = ("^VIX", "CBOE Volatility Index", "Volatility")


# ─────────────────────────────────────────────────────────────────
# Pending listings — tickers that are in the universe lists above but are
# NOT yet trading. all_entries() excludes them until their debut date, then
# auto-includes them (no manual change). Add a confirmed IPO date here and
# the stock joins the live universe automatically on that day.
# ─────────────────────────────────────────────────────────────────
PENDING_LISTINGS: Dict[str, str] = {
    "SPCX": "2026-06-12",   # SpaceX — first trade on Nasdaq (largest IPO in history)
}


# ─────────────────────────────────────────────────────────────────
# Asset-class mapping
# ─────────────────────────────────────────────────────────────────

ASSET_CLASSES: Dict[str, str] = {}

for tkr, _, _ in INDICES + SECTOR_ETFS:
    ASSET_CLASSES[tkr] = "etf"
for tkr, _, _ in MEGA_CAPS + TECH_GROWTH:
    ASSET_CLASSES[tkr] = "equity"
for tkr, _, _ in CRYPTO:
    ASSET_CLASSES[tkr] = "crypto"
for tkr, _, _ in COMMODITIES:
    ASSET_CLASSES[tkr] = "etf"   # treat commodity ETFs as etf-class
for tkr, _, _ in BONDS_RATES + FX_MACRO:
    ASSET_CLASSES[tkr] = "etf"


# ─────────────────────────────────────────────────────────────────
# Public accessors
# ─────────────────────────────────────────────────────────────────

def all_entries() -> List[Tuple[str, str, str]]:
    """Return every (ticker, name, sector) entry across the core + expanded
    universes. Deduped by ticker. Tickers in PENDING_LISTINGS are excluded
    until their listing date (so we don't price/debate a stock that isn't
    trading yet) and auto-activate on that date — no manual change needed."""
    base = (
        INDICES + SECTOR_ETFS + MEGA_CAPS + TECH_GROWTH +
        CRYPTO + COMMODITIES + BONDS_RATES + FX_MACRO
    )
    try:
        from .expanded import build_expanded_universe
        expanded = build_expanded_universe()
    except Exception:
        expanded = []
    today = datetime.now(timezone.utc).date()
    seen = set()
    out = []
    for entry in base + expanded:
        tkr = entry[0]
        if tkr in seen:
            continue
        # skip not-yet-listed tickers until their debut date
        ld = PENDING_LISTINGS.get(tkr)
        if ld:
            try:
                if today < datetime.strptime(ld, "%Y-%m-%d").date():
                    continue
            except Exception:
                pass
        seen.add(tkr)
        out.append(entry)
    return out


def all_tickers() -> List[str]:
    return [tkr for tkr, _, _ in all_entries()]


def get_meta(ticker: str) -> Tuple[str, str, str]:
    """Return (ticker, name, sector) for a known ticker, or defaults."""
    for tkr, name, sector in all_entries():
        if tkr == ticker:
            return tkr, name, sector
    return ticker, ticker, "Unknown"


def asset_class_of(ticker: str) -> str:
    return ASSET_CLASSES.get(ticker, "equity")


# Forex / commodity macro ETFs — tradeable, but NOT the stock mission.
_MACRO_ETFS = {
    "UUP", "FXE", "FXY", "FXF", "FXB", "FXC", "FXA", "CYB", "UDN", "USDU",
    "GLD", "SLV", "IAU", "GDX", "GDXJ", "USO", "UNG", "DBC", "PDBC", "DBA", "CPER",
}


def is_equity_ticker(ticker) -> bool:
    """True if `ticker` is a US equity / equity-ETF — the stock mission.

    Excludes crypto (``-USD`` / ``USDT`` pairs, detected structurally so it also
    catches off-universe compounder coins like BONK-USD) and forex/commodity
    macro ETFs. Used to keep the learning loop and edge measurement focused on
    stocks regardless of what happens to get scored. Defaults to False on empty
    input so unknown/blank tickers never sneak into the stock-only learning.
    """
    t = (ticker or "").upper()
    if not t:
        return False
    if t.endswith("-USD") or t.endswith("-USDT") or t.endswith("USDT") or "-USD" in t:
        return False
    if t in _MACRO_ETFS:
        return False
    return True


def total_count() -> int:
    return len(all_entries())
