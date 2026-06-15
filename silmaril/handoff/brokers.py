"""
silmaril.handoff.brokers — broker deeplinks for trade plans.

Each plan in the dashboard gets a row of broker buttons next to the
LLM handoff buttons. Tapping a broker opens that broker's asset page
where the user reviews and places the trade themselves.

We do NOT prefill orders. That would be misleading and likely
unlicensed. We open the right page on the right venue.
"""

from __future__ import annotations
from typing import Dict, List


# Fee strings shown next to each button. Approximate; verify before trusting.
BROKERS = [
    {
        "name": "Robinhood", "key": "robinhood",
        "equity_url": "https://robinhood.com/stocks/{ticker}",
        "crypto_url": "https://robinhood.com/crypto/{ticker_base}",
        "fees_equity": "$0 commission",
        "fees_crypto": "~30 bps spread",
    },
    {
        "name": "Fidelity", "key": "fidelity",
        "equity_url": "https://digital.fidelity.com/prgw/digital/research/quote/dashboard/summary?symbol={ticker}",
        "crypto_url": "https://www.fidelity.com/crypto/overview",
        "fees_equity": "$0 commission",
        "fees_crypto": "~1% spread",
    },
    {
        "name": "Schwab", "key": "schwab",
        "equity_url": "https://www.schwab.com/research/stocks/quotes?symbol={ticker}",
        "crypto_url": None,
        "fees_equity": "$0 commission",
        "fees_crypto": None,
    },
    {
        "name": "IBKR", "key": "ibkr",
        "equity_url": "https://www.interactivebrokers.com/portal/?action=ACCT_MGMT_MAIN&symbol={ticker}",
        "crypto_url": "https://www.interactivebrokers.com/en/trading/cryptocurrency.php",
        "fees_equity": "$0–0.005/sh",
        "fees_crypto": "~18 bps",
    },
    {
        "name": "Webull", "key": "webull",
        "equity_url": "https://www.webull.com/quote/{ticker}",
        "crypto_url": "https://www.webull.com/crypto",
        "fees_equity": "$0 commission",
        "fees_crypto": "~100 bps spread",
    },
    {
        "name": "Coinbase", "key": "coinbase",
        "equity_url": None,
        "crypto_url": "https://www.coinbase.com/price/{ticker_base_lower}",
        "fees_equity": None,
        "fees_crypto": "~40 bps taker",
    },
    {
        "name": "Kraken", "key": "kraken",
        "equity_url": None,
        "crypto_url": "https://www.kraken.com/prices/{ticker_base_lower}",
        "fees_equity": None,
        "fees_crypto": "~26 bps maker / 40 bps taker",
    },
    {
        "name": "Alpaca", "key": "alpaca",
        "equity_url": "https://app.alpaca.markets/",
        "crypto_url": "https://app.alpaca.markets/",
        "fees_equity": "$0 commission",
        "fees_crypto": "0%",
    },
]


def build_broker_links(ticker: str, asset_class: str) -> List[Dict]:
    """Return broker entries applicable to this asset, with URL filled in."""
    is_crypto = asset_class == "crypto" or ticker.endswith("-USD")
    base = ticker.replace("-USD", "")
    out = []
    for b in BROKERS:
        if is_crypto:
            url = b.get("crypto_url")
            fee = b.get("fees_crypto")
        else:
            url = b.get("equity_url")
            fee = b.get("fees_equity")
        if not url or not fee:
            continue
        url = (url
               .replace("{ticker}", ticker)
               .replace("{ticker_base}", base)
               .replace("{ticker_base_lower}", base.lower()))
        out.append({"name": b["name"], "url": url, "fee_label": fee, "key": b["key"]})
    return out
