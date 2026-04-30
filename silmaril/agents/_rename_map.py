"""
silmaril.agents._rename_map — Single source of truth for agent names.

Old codename -> new professional codename + display label + one-liner.
Specialist agents (Baron, Steadfast, Scrooge, Midas, Cryptobro, JRR_Token,
Sports_Bro) keep their identities.

Frontend reads from this map for display labels.
"""

AGENT_RENAME_MAP = {
    # Old -> (new codename, display label, one-line strategy)
    "AEGIS":       ("GUARDIAN",         "Guardian",          "Capital preservation; defensive veto"),
    "FORGE":       ("TECH_MOMENTUM",    "Tech Momentum",     "Tech-sector leadership and breakouts"),
    "THUNDERHEAD": ("CRYPTO_MOMENTUM",  "Crypto Momentum",   "Crypto volatility breakouts"),
    "JADE":        ("BIOTECH",          "Biotech",           "Healthcare and FDA-catalyst plays"),
    "VEIL":        ("SENTIMENT",        "Sentiment",         "Sentiment divergence from price"),
    "KESTREL":     ("OVERSOLD",         "Oversold",          "Naive RSI mean reversion"),
    "KESTREL+":    ("REVERTER",         "Reverter",          "Hurst-confirmed mean reversion"),
    "KESTREL_PLUS":("REVERTER",         "Reverter",          "Hurst-confirmed mean reversion"),
    "OBSIDIAN":    ("COMMODITY",        "Commodity",         "Energy, metals, hard assets"),
    "ZENITH":      ("TREND_FOLLOWER",   "Trend Follower",    "Long-duration momentum"),
    "WEAVER":      ("CORRELATOR",       "Correlator",        "Cross-asset relationships"),
    "HEX":         ("BEAR_WATCH",       "Bear Watch",        "Volatility-regime defensive"),
    "SYNTH":       ("DECORRELATE",      "Decorrelate",       "Correlation-break detection"),
    "SPECK":       ("SMALL_CAP",        "Small Cap",         "Small-cap sentiment + flows"),
    "VESPA":       ("PRE_EARNINGS",     "Pre-Earnings",      "Pre-earnings positioning"),
    "MAGUS":       ("MACROSCOPE",       "Macroscope",        "Macro and seasonality"),
    "TALON":       ("BREADTH",          "Breadth",           "Index breadth and structure"),
    "CICADA":      ("POST_EARNINGS",    "Post-Earnings",     "Post-earnings drift"),
    "NIGHTSHADE":  ("INSIDER",          "Insider",           "Form 4 insider transactions"),
    "BARNACLE":    ("WHALE_FOLLOW",     "Whale Follow",      "13F whale filings"),
    "NOMAD":       ("ADR_ARB",          "ADR Arbitrage",     "Cross-border ADR mispricing"),
    "ATLAS":       ("REGIME_TAGGER",    "Regime Tagger",     "Emits regime tag (no per-asset votes)"),

    # Specialists — IDENTITY PRESERVED
    "BARON":       ("BARON",            "Baron",             "Oil specialist"),
    "STEADFAST":   ("STEADFAST",        "Steadfast",         "Crown-jewels long-only"),
    "SCROOGE":     ("SCROOGE",          "Scrooge",           "$1 compounder — equities"),
    "MIDAS":       ("MIDAS",            "Midas",             "$1 compounder — gold/FX"),
    "CRYPTOBRO":   ("CRYPTOBRO",        "Crypto Bro",        "$1 compounder — top-100 crypto"),
    "JRR_TOKEN":   ("JRR_TOKEN",        "JRR Token",         "$1 compounder — memecoins"),
    "SPORTS_BRO":  ("SPORTS_BRO",       "Sports Bro",        "Prediction markets compounder"),

    # NEW agents in Alpha 2.0
    "CONTRARIAN":  ("CONTRARIAN",       "Contrarian",        "Crowded-trade fade detector"),
    "SHORT_ALPHA": ("SHORT_ALPHA",      "Short Alpha",       "Daily-move short specialist (catalysts)"),
}


def display_label(codename: str) -> str:
    if codename in AGENT_RENAME_MAP:
        return AGENT_RENAME_MAP[codename][1]
    for old, (new, label, _) in AGENT_RENAME_MAP.items():
        if new == codename:
            return label
    return codename


def new_codename(old_codename: str) -> str:
    if old_codename in AGENT_RENAME_MAP:
        return AGENT_RENAME_MAP[old_codename][0]
    return old_codename


def strategy_one_liner(codename: str) -> str:
    if codename in AGENT_RENAME_MAP:
        return AGENT_RENAME_MAP[codename][2]
    for old, (new, _, strat) in AGENT_RENAME_MAP.items():
        if new == codename:
            return strat
    return ""


def all_new_codenames() -> list:
    """De-duplicated list of all current codenames (post-rename)."""
    seen = []
    for _, (new, _, _) in AGENT_RENAME_MAP.items():
        if new not in seen:
            seen.append(new)
    return seen
