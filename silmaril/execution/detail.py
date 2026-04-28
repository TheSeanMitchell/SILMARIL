"""
silmaril.execution.detail — Professional trade execution metadata.

Every trade SILMARIL produces — whether from a trade plan, a SCROOGE rotation,
or a MIDAS allocation — gets wrapped in execution metadata that mirrors what
a real professional trade would look like:

  • Order ID and timestamp (submit + fill)
  • Exchange and venue
  • Broker routing and account
  • Funding source (cash account, simulated wallet)
  • Available balance before/after
  • Order type, time-in-force
  • Fill details (shares, price, time)
  • Settlement date (T+2 for equities, instant for crypto)
  • Fee breakdown (SEC Section 31, FINRA TAF, spread cost, broker commission)

All simulated. No orders leave the machine. But the numbers use real 2025
fee schedules so the dashboard shows what the trade would actually cost
in reality.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Dict, Optional


# ─────────────────────────────────────────────────────────────────
# Ticker → primary listing exchange
# ─────────────────────────────────────────────────────────────────

_NASDAQ = {
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    "AMD", "AVGO", "QCOM", "INTC", "MU", "ADBE", "NFLX", "COST",
    "CRWD", "PANW", "PLTR", "SNOW", "ASML", "TSM", "QQQ", "SMH", "SOXX",
    "TLT", "IEF", "SHY",
}
_NYSE = {
    "JPM", "V", "MA", "JNJ", "UNH", "LLY", "XOM", "CVX", "HD", "PG",
    "KO", "WMT", "DIS", "BRK-B", "ORCL", "CRM", "UBER", "SHOP", "NOW",
}
_NYSE_ARCA = {
    "SPY", "DIA", "IWM", "VTI", "EFA", "EEM",
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB",
    "XLRE", "XLC", "IGV", "ARKK",
    "GLD", "SLV", "IAU", "SIVR", "PPLT", "PALL",
    "USO", "UNG", "DBC", "CPER",
    "HYG", "LQD", "UUP", "FXE", "FXY", "FXF",
}
_COINBASE = {"BTC-USD", "ETH-USD", "SOL-USD"}


def exchange_for(ticker: str) -> str:
    t = ticker.upper()
    if t in _NASDAQ:      return "NASDAQ"
    if t in _NYSE:        return "NYSE"
    if t in _NYSE_ARCA:   return "NYSE Arca"
    if t in _COINBASE:    return "Coinbase Advanced Trade"
    if t == "^VIX":       return "CBOE"
    return "NYSE Arca"


def venue_description(exchange: str) -> str:
    """A short parenthetical describing what the exchange actually is."""
    return {
        "NASDAQ":                 "electronic equity exchange",
        "NYSE":                   "auction-based equity exchange",
        "NYSE Arca":              "all-electronic ETF/options exchange",
        "Coinbase Advanced Trade": "US-regulated crypto exchange",
        "CBOE":                   "options and volatility index exchange",
    }.get(exchange, "registered securities exchange")


# ─────────────────────────────────────────────────────────────────
# Broker + account profiles
# ─────────────────────────────────────────────────────────────────

def broker_for(asset_class: str) -> str:
    if asset_class == "crypto":
        return "Coinbase (simulated wallet)"
    return "Interactive Brokers (simulated paper account)"


def account_label_for(asset_class: str) -> str:
    return {
        "equity": "EQUITY-CASH-SIM-001",
        "etf":    "EQUITY-CASH-SIM-001",
        "crypto": "CRYPTO-WALLET-SIM-001",
    }.get(asset_class, "SIM-CASH-001")


def funding_source_for(asset_class: str) -> str:
    return {
        "equity": "ACH funding from simulated bank account (routed via broker cash sweep)",
        "etf":    "ACH funding from simulated bank account (routed via broker cash sweep)",
        "crypto": "Internal USDC balance (simulated deposit from cash sweep)",
    }.get(asset_class, "Internal simulated wallet")


# ─────────────────────────────────────────────────────────────────
# Settlement
# ─────────────────────────────────────────────────────────────────

_T_PLUS_1 = {"equity", "etf"}  # US equities moved to T+1 in May 2024


def settlement_date(trade_date: datetime, asset_class: str) -> str:
    if asset_class in _T_PLUS_1:
        d = trade_date
        added = 0
        while added < 1:
            d += timedelta(days=1)
            if d.weekday() < 5:
                added += 1
        return d.date().isoformat()
    return trade_date.date().isoformat()  # crypto: instant


# ─────────────────────────────────────────────────────────────────
# Fee modeling — 2025 US rates
# ─────────────────────────────────────────────────────────────────

_LIQUID_ETFS = {"SPY", "QQQ", "DIA", "IWM", "VTI", "GLD", "SLV", "TLT", "HYG",
                "XLK", "XLF", "XLE", "XLV", "XLY"}
_MEGA_EQUITIES = {"AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
                  "JPM", "XOM", "V", "MA", "JNJ"}


def _spread_bps(ticker: str, asset_class: str) -> int:
    t = ticker.upper()
    if asset_class == "crypto":    return 8
    if t in _LIQUID_ETFS:           return 1
    if t in _MEGA_EQUITIES:         return 1
    if asset_class == "etf":        return 4
    return 3  # default equity


def compute_fees(
    ticker: str,
    asset_class: str,
    side: str,
    shares: float,
    price: float,
) -> Dict[str, float]:
    notional = shares * price
    commission = 0.0
    sec_31 = 0.0
    finra_taf = 0.0

    if asset_class in _T_PLUS_1:
        # US equities: SEC Section 31 fee on sells only, FINRA TAF on sells only
        if side == "SELL":
            sec_31 = notional * 27.80 / 1_000_000        # $27.80 per $1M
            finra_taf = min(shares * 0.000166, 9.30)     # capped per trade
        # Most modern retail brokers charge $0 on equities
    elif asset_class == "crypto":
        # Coinbase Advanced taker fee on market orders (simulated)
        commission = notional * 0.0040

    spread_bps = _spread_bps(ticker, asset_class)
    spread_cost = notional * spread_bps / 10_000

    total = commission + sec_31 + finra_taf + spread_cost

    return {
        "commission":    round(commission, 6),
        "sec_section_31": round(sec_31, 6),
        "finra_taf":     round(finra_taf, 6),
        "spread_cost":   round(spread_cost, 6),
        "total":         round(total, 6),
        "notes": (
            f"Spread estimate: {spread_bps} bps. "
            + ("Crypto taker fee 0.40%. " if asset_class == "crypto" else "")
            + ("Zero commission (IBKR Lite/TD-class simulated). " if asset_class in _T_PLUS_1 else "")
        ).strip(),
    }


# ─────────────────────────────────────────────────────────────────
# Main builder
# ─────────────────────────────────────────────────────────────────

def build_execution(
    ticker: str,
    asset_class: str,
    side: str,                       # "BUY" or "SELL"
    shares: float,
    price: float,
    available_before: float,
    trade_date: Optional[datetime] = None,
) -> Dict:
    """Wrap a simulated trade in full execution metadata."""
    now = trade_date or datetime.now(timezone.utc)
    ts = now.isoformat(timespec="seconds")

    fees = compute_fees(ticker, asset_class, side, shares, price)
    notional = shares * price
    if side == "BUY":
        net_cost = notional + fees["total"]
        net_proceeds = None
        available_after = available_before - net_cost
    else:
        net_cost = None
        net_proceeds = notional - fees["total"]
        available_after = available_before + net_proceeds

    exchange = exchange_for(ticker)

    # Fill time is plausibly 1-3 seconds after submit for a market order
    fill_time = (now + timedelta(seconds=2)).isoformat(timespec="seconds")

    return {
        "order_id": f"SIM-{now.strftime('%Y%m%d-%H%M%S')}-{ticker.replace('-', '')}-{side[0]}",
        "side": side,
        "ticker": ticker,
        "asset_class": asset_class,
        "exchange": exchange,
        "venue": venue_description(exchange),
        "broker": broker_for(asset_class),
        "order_type": "MARKET",
        "time_in_force": "DAY",
        "submitted_at_utc": ts,
        "filled_at_utc": fill_time,
        "settlement_date": settlement_date(now, asset_class),
        "account": {
            "label":          account_label_for(asset_class),
            "type":           "Cash Account" if asset_class != "crypto" else "Crypto Wallet",
            "broker":         broker_for(asset_class),
            "funding_source": funding_source_for(asset_class),
            "balance_before": round(available_before, 4),
            "balance_after":  round(available_after, 4),
        },
        "fills": [{
            "shares":    round(shares, 6),
            "price":     round(price, 4),
            "timestamp": fill_time,
            "venue":     exchange,
        }],
        "avg_fill_price": round(price, 4),
        "gross_notional": round(notional, 4),
        "fees":           fees,
        "net_cost":       round(net_cost, 4) if net_cost is not None else None,
        "net_proceeds":   round(net_proceeds, 4) if net_proceeds is not None else None,
        "disclaimer": (
            "Simulated execution — no live orders were placed on any exchange. "
            "Fees modeled on US market structure: SEC Section 31 ($27.80/$1M of sale "
            "proceeds), FINRA Trading Activity Fee ($0.000166/share on sells, capped $9.30), "
            "Coinbase Advanced taker 0.40% for crypto. Spread cost estimated per ticker."
        ),
    }
