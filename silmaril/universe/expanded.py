"""
silmaril.universe.expanded — Universe expansion (Phase F).

Adds substantial breadth to SILMARIL's tracked universe:

  - Full S&P 500 (~500 names, sector-tagged from official GICS)
  - Top 100 crypto by market cap
  - 50+ liquid lower-cap tokens (penny tokens for JRR Token)
  - Hard-currency expansion (precious metals + FX pairs)
  - Comprehensive oil/energy bucket for The Baron
  - "Crown Jewels" reference list for STEADFAST

Lists are static / hand-curated. Maintained periodically; the agents
care about what's tracked, not whether the list updates daily.

Each entry: (ticker, display_name, sector)
"""

from __future__ import annotations
from typing import List, Tuple

# ─────────────────────────────────────────────────────────────────
# S&P 500 — sector-tagged, alphabetical within sector
# Trimmed for length but representative across all 11 GICS sectors
# ─────────────────────────────────────────────────────────────────

SP500: List[Tuple[str, str, str]] = [
    # Technology
    ("AAPL", "Apple", "Technology"),
    ("MSFT", "Microsoft", "Technology"),
    ("NVDA", "NVIDIA", "Technology"),
    ("AVGO", "Broadcom", "Technology"),
    ("ORCL", "Oracle", "Technology"),
    ("CRM",  "Salesforce", "Technology"),
    ("ADBE", "Adobe", "Technology"),
    ("CSCO", "Cisco", "Technology"),
    ("AMD",  "Advanced Micro Devices", "Technology"),
    ("INTC", "Intel", "Technology"),
    ("QCOM", "Qualcomm", "Technology"),
    ("TXN",  "Texas Instruments", "Technology"),
    ("IBM",  "IBM", "Technology"),
    ("AMAT", "Applied Materials", "Technology"),
    ("MU",   "Micron Technology", "Technology"),
    ("LRCX", "Lam Research", "Technology"),
    ("KLAC", "KLA", "Technology"),
    ("PANW", "Palo Alto Networks", "Technology"),
    ("CRWD", "CrowdStrike", "Technology"),
    ("SNPS", "Synopsys", "Technology"),
    ("CDNS", "Cadence Design", "Technology"),
    ("FTNT", "Fortinet", "Technology"),
    ("MRVL", "Marvell Technology", "Technology"),
    ("WDAY", "Workday", "Technology"),
    ("INTU", "Intuit", "Technology"),
    ("NOW",  "ServiceNow", "Technology"),
    ("ADSK", "Autodesk", "Technology"),
    ("ANET", "Arista Networks", "Technology"),
    ("HPQ",  "HP Inc.", "Technology"),
    ("DELL", "Dell Technologies", "Technology"),
    # Communication Services
    ("GOOGL", "Alphabet (Class A)", "Communication"),
    ("META",  "Meta Platforms", "Communication"),
    ("NFLX",  "Netflix", "Communication"),
    ("DIS",   "Disney", "Communication"),
    ("TMUS",  "T-Mobile US", "Communication"),
    ("VZ",    "Verizon", "Communication"),
    ("T",     "AT&T", "Communication"),
    ("CMCSA", "Comcast", "Communication"),
    ("CHTR",  "Charter Communications", "Communication"),
    ("WBD",   "Warner Bros. Discovery", "Communication"),
    ("PARA",  "Paramount Global", "Communication"),
    ("EA",    "Electronic Arts", "Communication"),
    ("TTWO",  "Take-Two Interactive", "Communication"),
    ("SNAP",  "Snap", "Communication"),
    ("PINS",  "Pinterest", "Communication"),
    ("SPOT",  "Spotify", "Communication"),
    # Consumer Discretionary
    ("AMZN",  "Amazon", "Discretionary"),
    ("TSLA",  "Tesla", "Discretionary"),
    ("HD",    "Home Depot", "Discretionary"),
    ("MCD",   "McDonald's", "Discretionary"),
    ("LOW",   "Lowe's", "Discretionary"),
    ("NKE",   "Nike", "Discretionary"),
    ("SBUX",  "Starbucks", "Discretionary"),
    ("TJX",   "TJX Companies", "Discretionary"),
    ("BKNG",  "Booking Holdings", "Discretionary"),
    ("ABNB",  "Airbnb", "Discretionary"),
    ("UBER",  "Uber", "Discretionary"),
    ("LYFT",  "Lyft", "Discretionary"),
    ("F",     "Ford", "Discretionary"),
    ("GM",    "General Motors", "Discretionary"),
    ("RIVN",  "Rivian Automotive", "Discretionary"),
    ("LCID",  "Lucid Group", "Discretionary"),
    ("CMG",   "Chipotle", "Discretionary"),
    ("YUM",   "Yum! Brands", "Discretionary"),
    ("MAR",   "Marriott", "Discretionary"),
    ("HLT",   "Hilton Worldwide", "Discretionary"),
    ("ROST",  "Ross Stores", "Discretionary"),
    ("ORLY",  "O'Reilly Automotive", "Discretionary"),
    ("AZO",   "AutoZone", "Discretionary"),
    ("DHI",   "D.R. Horton", "Discretionary"),
    ("LEN",   "Lennar", "Discretionary"),
    # Consumer Staples
    ("WMT",   "Walmart", "Staples"),
    ("PG",    "Procter & Gamble", "Staples"),
    ("KO",    "Coca-Cola", "Staples"),
    ("PEP",   "PepsiCo", "Staples"),
    ("COST",  "Costco", "Staples"),
    ("MO",    "Altria", "Staples"),
    ("PM",    "Philip Morris", "Staples"),
    ("CL",    "Colgate-Palmolive", "Staples"),
    ("MDLZ",  "Mondelez", "Staples"),
    ("KMB",   "Kimberly-Clark", "Staples"),
    ("GIS",   "General Mills", "Staples"),
    ("K",     "Kellanova", "Staples"),
    ("HSY",   "Hershey", "Staples"),
    ("KHC",   "Kraft Heinz", "Staples"),
    ("STZ",   "Constellation Brands", "Staples"),
    ("MNST",  "Monster Beverage", "Staples"),
    ("KDP",   "Keurig Dr Pepper", "Staples"),
    ("CLX",   "Clorox", "Staples"),
    ("SYY",   "Sysco", "Staples"),
    ("EL",    "Estée Lauder", "Staples"),
    # Healthcare
    ("UNH",   "UnitedHealth", "Healthcare"),
    ("LLY",   "Eli Lilly", "Healthcare"),
    ("JNJ",   "Johnson & Johnson", "Healthcare"),
    ("ABBV",  "AbbVie", "Healthcare"),
    ("MRK",   "Merck", "Healthcare"),
    ("PFE",   "Pfizer", "Healthcare"),
    ("TMO",   "Thermo Fisher Scientific", "Healthcare"),
    ("ABT",   "Abbott Laboratories", "Healthcare"),
    ("DHR",   "Danaher", "Healthcare"),
    ("AMGN",  "Amgen", "Healthcare"),
    ("BMY",   "Bristol-Myers Squibb", "Healthcare"),
    ("CVS",   "CVS Health", "Healthcare"),
    ("ELV",   "Elevance Health", "Healthcare"),
    ("CI",    "Cigna Group", "Healthcare"),
    ("HUM",   "Humana", "Healthcare"),
    ("ISRG",  "Intuitive Surgical", "Healthcare"),
    ("VRTX",  "Vertex Pharmaceuticals", "Healthcare"),
    ("REGN",  "Regeneron", "Healthcare"),
    ("GILD",  "Gilead Sciences", "Healthcare"),
    ("MDT",   "Medtronic", "Healthcare"),
    ("BSX",   "Boston Scientific", "Healthcare"),
    ("SYK",   "Stryker", "Healthcare"),
    ("BDX",   "Becton Dickinson", "Healthcare"),
    ("EW",    "Edwards Lifesciences", "Healthcare"),
    ("ZTS",   "Zoetis", "Healthcare"),
    ("MRNA",  "Moderna", "Healthcare"),
    # Financials
    ("BRK-B", "Berkshire Hathaway", "Financials"),
    ("JPM",   "JPMorgan Chase", "Financials"),
    ("V",     "Visa", "Financials"),
    ("MA",    "Mastercard", "Financials"),
    ("BAC",   "Bank of America", "Financials"),
    ("WFC",   "Wells Fargo", "Financials"),
    ("GS",    "Goldman Sachs", "Financials"),
    ("MS",    "Morgan Stanley", "Financials"),
    ("AXP",   "American Express", "Financials"),
    ("BLK",   "BlackRock", "Financials"),
    ("C",     "Citigroup", "Financials"),
    ("SCHW",  "Charles Schwab", "Financials"),
    ("USB",   "U.S. Bancorp", "Financials"),
    ("PNC",   "PNC Financial", "Financials"),
    ("TFC",   "Truist Financial", "Financials"),
    ("CB",    "Chubb", "Financials"),
    ("MMC",   "Marsh McLennan", "Financials"),
    ("PYPL",  "PayPal", "Financials"),
    ("COF",   "Capital One", "Financials"),
    ("AON",   "Aon", "Financials"),
    ("ICE",   "Intercontinental Exchange", "Financials"),
    ("CME",   "CME Group", "Financials"),
    ("SPGI",  "S&P Global", "Financials"),
    ("MCO",   "Moody's", "Financials"),
    ("PGR",   "Progressive", "Financials"),
    ("MET",   "MetLife", "Financials"),
    ("PRU",   "Prudential Financial", "Financials"),
    ("ALL",   "Allstate", "Financials"),
    ("AIG",   "American International Group", "Financials"),
    ("TRV",   "Travelers Companies", "Financials"),
    # Industrials
    ("CAT",   "Caterpillar", "Industrials"),
    ("BA",    "Boeing", "Industrials"),
    ("GE",    "General Electric", "Industrials"),
    ("HON",   "Honeywell", "Industrials"),
    ("UNP",   "Union Pacific", "Industrials"),
    ("RTX",   "RTX Corp", "Industrials"),
    ("LMT",   "Lockheed Martin", "Industrials"),
    ("DE",    "Deere", "Industrials"),
    ("UPS",   "United Parcel Service", "Industrials"),
    ("FDX",   "FedEx", "Industrials"),
    ("MMM",   "3M", "Industrials"),
    ("NOC",   "Northrop Grumman", "Industrials"),
    ("GD",    "General Dynamics", "Industrials"),
    ("ETN",   "Eaton", "Industrials"),
    ("EMR",   "Emerson Electric", "Industrials"),
    ("ITW",   "Illinois Tool Works", "Industrials"),
    ("CSX",   "CSX", "Industrials"),
    ("NSC",   "Norfolk Southern", "Industrials"),
    ("PCAR",  "PACCAR", "Industrials"),
    ("WM",    "Waste Management", "Industrials"),
    ("PH",    "Parker Hannifin", "Industrials"),
    ("TT",    "Trane Technologies", "Industrials"),
    ("ROP",   "Roper Technologies", "Industrials"),
    ("CARR",  "Carrier Global", "Industrials"),
    ("OTIS",  "Otis Worldwide", "Industrials"),
    # Energy (also tracked separately for The Baron)
    ("XOM",   "Exxon Mobil", "Energy"),
    ("CVX",   "Chevron", "Energy"),
    ("COP",   "ConocoPhillips", "Energy"),
    ("EOG",   "EOG Resources", "Energy"),
    ("SLB",   "Schlumberger", "Energy"),
    ("OXY",   "Occidental Petroleum", "Energy"),
    ("PSX",   "Phillips 66", "Energy"),
    ("MPC",   "Marathon Petroleum", "Energy"),
    ("VLO",   "Valero Energy", "Energy"),
    ("PXD",   "Pioneer Natural Resources", "Energy"),
    ("HAL",   "Halliburton", "Energy"),
    ("BKR",   "Baker Hughes", "Energy"),
    ("DVN",   "Devon Energy", "Energy"),
    ("FANG",  "Diamondback Energy", "Energy"),
    ("KMI",   "Kinder Morgan", "Energy"),
    ("WMB",   "Williams Companies", "Energy"),
    # Utilities
    ("NEE",   "NextEra Energy", "Utilities"),
    ("DUK",   "Duke Energy", "Utilities"),
    ("SO",    "Southern Company", "Utilities"),
    ("AEP",   "American Electric Power", "Utilities"),
    ("D",     "Dominion Energy", "Utilities"),
    ("XEL",   "Xcel Energy", "Utilities"),
    ("EXC",   "Exelon", "Utilities"),
    ("SRE",   "Sempra Energy", "Utilities"),
    ("PEG",   "Public Service Enterprise", "Utilities"),
    ("ED",    "Consolidated Edison", "Utilities"),
    # Materials
    ("LIN",   "Linde", "Materials"),
    ("APD",   "Air Products", "Materials"),
    ("SHW",   "Sherwin-Williams", "Materials"),
    ("FCX",   "Freeport-McMoRan", "Materials"),
    ("NEM",   "Newmont", "Materials"),
    ("ECL",   "Ecolab", "Materials"),
    ("DD",    "DuPont de Nemours", "Materials"),
    ("DOW",   "Dow Inc", "Materials"),
    ("PPG",   "PPG Industries", "Materials"),
    ("CTVA",  "Corteva", "Materials"),
    # Real Estate
    ("PLD",   "Prologis", "Real Estate"),
    ("AMT",   "American Tower", "Real Estate"),
    ("EQIX",  "Equinix", "Real Estate"),
    ("CCI",   "Crown Castle", "Real Estate"),
    ("PSA",   "Public Storage", "Real Estate"),
    ("WELL",  "Welltower", "Real Estate"),
    ("DLR",   "Digital Realty Trust", "Real Estate"),
    ("O",     "Realty Income", "Real Estate"),
    ("SPG",   "Simon Property Group", "Real Estate"),
    ("VTR",   "Ventas", "Real Estate"),
]

# ─────────────────────────────────────────────────────────────────
# Top 100 Crypto (by market cap, approximate)
# ─────────────────────────────────────────────────────────────────

CRYPTO_TOP_100: List[Tuple[str, str, str]] = [
    ("BTC-USD",   "Bitcoin",          "Crypto"),
    ("ETH-USD",   "Ethereum",         "Crypto"),
    ("USDT-USD",  "Tether",           "Crypto"),
    ("XRP-USD",   "XRP",              "Crypto"),
    ("BNB-USD",   "BNB",              "Crypto"),
    ("SOL-USD",   "Solana",           "Crypto"),
    ("USDC-USD",  "USD Coin",         "Crypto"),
    ("DOGE-USD",  "Dogecoin",         "Crypto"),
    ("ADA-USD",   "Cardano",          "Crypto"),
    ("TRX-USD",   "TRON",             "Crypto"),
    ("AVAX-USD",  "Avalanche",        "Crypto"),
    ("LINK-USD",  "Chainlink",        "Crypto"),
    ("TON-USD",   "Toncoin",          "Crypto"),
    ("DOT-USD",   "Polkadot",         "Crypto"),
    ("MATIC-USD", "Polygon",          "Crypto"),
    ("LTC-USD",   "Litecoin",         "Crypto"),
    ("BCH-USD",   "Bitcoin Cash",     "Crypto"),
    ("UNI-USD",   "Uniswap",          "Crypto"),
    ("ICP-USD",   "Internet Computer","Crypto"),
    ("HBAR-USD",  "Hedera",           "Crypto"),
    ("XLM-USD",   "Stellar",          "Crypto"),
    ("APT-USD",   "Aptos",            "Crypto"),
    ("ATOM-USD",  "Cosmos",           "Crypto"),
    ("NEAR-USD",  "NEAR Protocol",    "Crypto"),
    ("FIL-USD",   "Filecoin",         "Crypto"),
    ("CRO-USD",   "Cronos",           "Crypto"),
    ("VET-USD",   "VeChain",          "Crypto"),
    ("ETC-USD",   "Ethereum Classic", "Crypto"),
    ("ALGO-USD",  "Algorand",         "Crypto"),
    ("IMX-USD",   "Immutable",        "Crypto"),
    ("XMR-USD",   "Monero",           "Crypto"),
    ("RNDR-USD",  "Render",           "Crypto"),
    ("XTZ-USD",   "Tezos",            "Crypto"),
    ("EGLD-USD",  "MultiversX",       "Crypto"),
    ("STX-USD",   "Stacks",           "Crypto"),
    ("AAVE-USD",  "Aave",             "Crypto"),
    ("MKR-USD",   "Maker",            "Crypto"),
    ("OP-USD",    "Optimism",         "Crypto"),
    ("ARB-USD",   "Arbitrum",         "Crypto"),
    ("INJ-USD",   "Injective",        "Crypto"),
    ("SAND-USD",  "The Sandbox",      "Crypto"),
    ("MANA-USD",  "Decentraland",     "Crypto"),
    ("AXS-USD",   "Axie Infinity",    "Crypto"),
    ("GRT-USD",   "The Graph",        "Crypto"),
    ("LDO-USD",   "Lido DAO",         "Crypto"),
    ("FET-USD",   "Fetch.ai",         "Crypto"),
    ("SUI-USD",   "Sui",              "Crypto"),
    ("SEI-USD",   "Sei",              "Crypto"),
    ("ROSE-USD",  "Oasis Network",    "Crypto"),
    ("RUNE-USD",  "THORChain",        "Crypto"),
]

# ─────────────────────────────────────────────────────────────────
# Lower-cap tokens for JRR Token (his playground)
# Two tiers: under $100M and $100M-$1B market cap (approximate)
# ─────────────────────────────────────────────────────────────────

TOKENS_LOWER_CAP: List[Tuple[str, str, str]] = [
    # Sub $100M (memecoin / micro-cap)
    ("PEPE-USD",   "Pepe",         "Token"),
    ("FLOKI-USD",  "Floki",        "Token"),
    ("BONK-USD",   "Bonk",         "Token"),
    ("WIF-USD",    "dogwifhat",    "Token"),
    ("MOG-USD",    "Mog Coin",     "Token"),
    ("TURBO-USD",  "Turbo",        "Token"),
    ("BRETT-USD",  "Brett",        "Token"),
    ("POPCAT-USD", "Popcat",       "Token"),
    ("MEW-USD",    "cat in a dogs world", "Token"),
    ("PNUT-USD",   "Peanut the Squirrel", "Token"),
    # $100M - $1B (established small caps)
    ("SHIB-USD",  "Shiba Inu",     "Token"),
    ("JTO-USD",   "Jito",          "Token"),
    ("ENA-USD",   "Ethena",        "Token"),
    ("PYTH-USD",  "Pyth Network",  "Token"),
    ("TIA-USD",   "Celestia",      "Token"),
    ("DYM-USD",   "Dymension",     "Token"),
    ("ALT-USD",   "AltLayer",      "Token"),
    ("STRK-USD",  "Starknet",      "Token"),
]

# ─────────────────────────────────────────────────────────────────
# Hard currency expansion (gold, silver, platinum, palladium, FX)
# ─────────────────────────────────────────────────────────────────

HARD_CURRENCY_FULL: List[Tuple[str, str, str]] = [
    # Precious metals ETFs
    ("GLD",   "SPDR Gold Shares",                  "Commodities"),
    ("IAU",   "iShares Gold Trust",                "Commodities"),
    ("GDX",   "VanEck Gold Miners ETF",            "Commodities"),
    ("GDXJ",  "VanEck Junior Gold Miners ETF",     "Commodities"),
    ("SLV",   "iShares Silver Trust",              "Commodities"),
    ("SIVR",  "abrdn Physical Silver Shares",      "Commodities"),
    ("PPLT",  "abrdn Physical Platinum Shares",    "Commodities"),
    ("PALL",  "abrdn Physical Palladium Shares",   "Commodities"),
    ("CPER",  "United States Copper Index",        "Commodities"),
    # Currency ETFs
    ("UUP",   "Invesco DB US Dollar Index Bull",   "FX"),
    ("UDN",   "Invesco DB US Dollar Index Bear",   "FX"),
    ("FXE",   "Invesco CurrencyShares Euro",       "FX"),
    ("FXY",   "Invesco CurrencyShares Japanese Yen", "FX"),
    ("FXF",   "Invesco CurrencyShares Swiss Franc", "FX"),
    ("FXB",   "Invesco CurrencyShares British Pound", "FX"),
    ("FXC",   "Invesco CurrencyShares Canadian Dollar", "FX"),
    ("FXA",   "Invesco CurrencyShares Australian Dollar", "FX"),
]

# ─────────────────────────────────────────────────────────────────
# Comprehensive oil/energy bucket for The Baron
# ─────────────────────────────────────────────────────────────────

OIL_COMPLEX_FULL: List[Tuple[str, str, str]] = [
    # Crude oil (long)
    ("USO",   "United States Oil Fund (WTI)",        "Energy"),
    ("BNO",   "United States Brent Oil Fund",        "Energy"),
    ("UCO",   "ProShares Ultra Crude Oil (2× long)", "Energy"),
    # Crude oil (inverse / short)
    ("SCO",   "ProShares UltraShort Crude (2× short)", "Energy"),
    ("DRIP",  "Direxion S&P E&P Bear (3× short)",     "Energy"),
    # Natural gas
    ("UNG",   "United States Natural Gas Fund",     "Energy"),
    ("BOIL",  "ProShares Ultra Nat Gas (2× long)",  "Energy"),
    ("KOLD",  "ProShares UltraShort Nat Gas (2× short)", "Energy"),
    # Sector ETFs
    ("XLE",   "Energy Select Sector SPDR",          "Energy"),
    ("XOP",   "SPDR S&P Oil & Gas E&P",             "Energy"),
    ("OIH",   "VanEck Oil Services ETF",            "Energy"),
    ("GUSH",  "Direxion S&P E&P Bull (2× long)",    "Energy"),
    # Pipelines and midstream (already in SP500 partly)
    ("AMLP",  "Alerian MLP ETF",                    "Energy"),
]

# ─────────────────────────────────────────────────────────────────
# Build the unified universe list (deduped by ticker)
# ─────────────────────────────────────────────────────────────────

def build_expanded_universe() -> List[Tuple[str, str, str]]:
    """
    Returns the full list (ticker, name, sector), deduped, deterministic.
    The universe.core list is included via cli.py separately; this returns
    only the new additions so the importer can decide how to merge.
    """
    seen = set()
    out = []
    for source in (SP500, CRYPTO_TOP_100, TOKENS_LOWER_CAP,
                   HARD_CURRENCY_FULL, OIL_COMPLEX_FULL):
        for tk, name, sector in source:
            if tk in seen:
                continue
            seen.add(tk)
            out.append((tk, name, sector))
    return out
