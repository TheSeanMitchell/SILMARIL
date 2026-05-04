"""
silmaril.execution.alpaca_paper — Free paper-trading bridge to Alpaca.

Alpaca's paper trading API is FREE (no real money, no fees). Every
consensus BUY/SELL signal becomes a real-shaped order in your paper
account, executed against simulated fills.

HARD GUARANTEE: This module is paper-only. Base URL is hardcoded.
There is no parameter, env-var, or secret that can flip this to live.
Live trading requires a separate, deliberately-named module that does
not currently exist in this codebase.

Setup:
  1. Create free account at https://alpaca.markets
  2. Generate paper-trading API keys
  3. Set GitHub secrets:
       ALPACA_API_KEY
       ALPACA_API_SECRET
  4. The daily.yml workflow calls this automatically after consensus phase
  5. State written to docs/data/alpaca_paper_state.json (PROTECTED)
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from silmaril.ingestion.market_hours import is_market_open

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    _HAS_ALPACA = True
except ImportError:
    _HAS_ALPACA = False


# HARDCODED — paper only. There is no override.
PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def _client() -> Optional["TradingClient"]:
    if not _HAS_ALPACA:
        return None
    api_key = os.environ.get("ALPACA_API_KEY")
    api_secret = os.environ.get("ALPACA_API_SECRET")
    if not api_key or not api_secret:
        return None
    return TradingClient(api_key, api_secret, paper=True)


def execute_consensus_signals(
    plans: List[Dict],
    state_path: Path,
    max_position_pct: float = 0.05,
    min_consensus_conviction: float = 0.45,
    max_total_positions: int = 15,
    enable_shorts: bool = True,
    all_debate_signals: Optional[Dict[str, str]] = None,
) -> Dict:
    """
    Send today's top trade plans to Alpaca paper-trading.

    plans: list of trade plan dicts (BUY-side ranked by conviction)
    state_path: docs/data/alpaca_paper_state.json
    max_position_pct: cap any single position at this % of equity
    min_consensus_conviction: only trade above this conviction
    max_total_positions: hard cap on concurrent positions
    enable_shorts: if True, SELL/STRONG_SELL signals open short positions
    all_debate_signals: {ticker: consensus_signal} for ALL debated tickers,
        not just those that made the top-plan cut. Required for correct exit
        logic — without this, positions whose tickers fall outside the top
        N plans are NEVER closed even when consensus flips to SELL.
        Pass debate_dicts from cli.py: {d['ticker']: d['consensus']['signal']}
    """
    state = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "enabled": False,
        "reason": "",
        "account": {},
        "orders_placed": [],
        "positions": [],
        "errors": [],
        "shorts_enabled": enable_shorts,
    }

    client = _client()
    if client is None:
        state["reason"] = (
            "alpaca-py not installed or ALPACA_API_KEY/SECRET not set. "
            "Skipping paper-trade execution."
        )
        _write(state_path, state)
        return state

    state["enabled"] = True

    try:
        account = client.get_account()
        equity = float(account.equity)
        state["account"] = {
            "equity": equity,
            "cash": float(account.cash),
            "status": str(account.status),
            "pattern_day_trader": bool(account.pattern_day_trader),
            "shorting_enabled": bool(account.shorting_enabled),
        }
    except Exception as e:
        state["errors"].append(f"account fetch: {type(e).__name__}: {e}")
        _write(state_path, state)
        return state

    try:
        existing = client.get_all_positions()
        state["positions"] = [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "side": str(p.side),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
            }
            for p in existing
        ]
    except Exception as e:
        state["errors"].append(f"positions fetch: {type(e).__name__}: {e}")
        existing = []

    held_long = {p.symbol for p in existing if str(p.side).lower() == "long"}
    held_short = {p.symbol for p in existing if str(p.side).lower() == "short"}
    n_positions = len(existing)
    available_slots = max(0, max_total_positions - n_positions)

    # ---- Market hours gate for equity orders ----
    # Crypto plans (asset_class == "crypto") bypass this gate — they trade 24/7.
    # Equity/ETF orders are only submitted when NYSE is open (Mon-Fri 9:30-4pm ET).
    # This prevents stale weekend signals from filling at Monday's open at wrong prices.
    equity_market_open = is_market_open("NYSE")
    if not equity_market_open:
        state["reason"] = (
            "NYSE closed — equity/ETF orders skipped. "
            "Crypto plans still processed. Run again during market hours for equity entries."
        )
        # Still process crypto exits and entries even when NYSE is closed
        plans = [p for p in plans if p.get("asset_class") == "crypto"]

    # ---- LONG entries ----
    long_actionable = [
        p for p in plans
        if (p.get("consensus_conviction") or 0) >= min_consensus_conviction
        and p.get("consensus_signal") in ("BUY", "STRONG_BUY")
        and p.get("ticker") not in held_long
        and p.get("asset_class", "equity") in ("equity", "etf")
    ]
    long_actionable.sort(key=lambda p: p.get("consensus_conviction", 0), reverse=True)

    for plan in long_actionable[:available_slots]:
        ticker = plan.get("ticker")
        try:
            position_dollars = equity * max_position_pct
            entry = float(plan.get("entry_price", 0)) or float(plan.get("price", 0))
            if entry <= 0:
                state["errors"].append(f"{ticker}: no entry price")
                continue
            qty = max(1, int(position_dollars / entry))
            order = MarketOrderRequest(
                symbol=ticker, qty=qty,
                side=OrderSide.BUY,
                time_in_force=TimeInForce.DAY,
            )
            placed = client.submit_order(order)
            state["orders_placed"].append({
                "ticker": ticker, "qty": qty, "side": "BUY",
                "alpaca_order_id": str(placed.id),
                "consensus_conviction": plan.get("consensus_conviction"),
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            })
            available_slots -= 1
        except Exception as e:
            state["errors"].append(f"{ticker} BUY: {type(e).__name__}: {e}")

    # ---- SHORT entries (only if enabled and account supports) ----
    if enable_shorts and state["account"].get("shorting_enabled"):
        short_actionable = [
            p for p in plans
            if (p.get("consensus_conviction") or 0) >= min_consensus_conviction
            and p.get("consensus_signal") in ("SELL", "STRONG_SELL")
            and p.get("ticker") not in held_short
            and p.get("ticker") not in held_long
            and p.get("asset_class", "equity") in ("equity", "etf")
        ]
        short_actionable.sort(key=lambda p: p.get("consensus_conviction", 0), reverse=True)

        for plan in short_actionable[:max(0, available_slots)]:
            ticker = plan.get("ticker")
            try:
                position_dollars = equity * (max_position_pct * 0.6)  # smaller for shorts
                entry = float(plan.get("entry_price", 0)) or float(plan.get("price", 0))
                if entry <= 0:
                    continue
                qty = max(1, int(position_dollars / entry))
                order = MarketOrderRequest(
                    symbol=ticker, qty=qty,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                )
                placed = client.submit_order(order)
                state["orders_placed"].append({
                    "ticker": ticker, "qty": qty, "side": "SHORT",
                    "alpaca_order_id": str(placed.id),
                    "consensus_conviction": plan.get("consensus_conviction"),
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                state["errors"].append(f"{ticker} SHORT: {type(e).__name__}: {e}")

    # ---- Exits: close positions whose latest consensus is opposite ----
    # ALPHA 2.0 FIX: Previously used only plan_signals (top N trade plans),
    # so any held ticker that fell outside the top-plan cut had signal=None
    # and was never closed — producing "buy only, never sell" behaviour.
    # Now we prefer all_debate_signals (every debated ticker's consensus)
    # and fall back to plan_signals only when the broader map isn't provided.
    plan_signals = {p.get("ticker"): p.get("consensus_signal") for p in plans}
    exit_signals = all_debate_signals if all_debate_signals else plan_signals
    for pos in existing:
        sig = exit_signals.get(pos.symbol)
        side = str(pos.side).lower()
        # Long position with SELL signal -> close
        # Short position with BUY signal -> close
        should_close = (
            (side == "long"  and sig in ("SELL", "STRONG_SELL", "HOLD")) or
            (side == "short" and sig in ("BUY",  "STRONG_BUY",  "HOLD"))
        )
        # Auto-close shorts after 3 days regardless (SHORT_ALPHA's rule)
        # The position object's avg_entry_time would tell us — Alpaca exposes this
        # For simplicity we rely on signal flip here

        if should_close:
            try:
                client.close_position(pos.symbol)
                state["orders_placed"].append({
                    "ticker": pos.symbol,
                    "qty": float(pos.qty),
                    "side": "CLOSE",
                    "alpaca_order_id": "close_position",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                state["errors"].append(f"{pos.symbol} CLOSE: {type(e).__name__}: {e}")

    _write(state_path, state)
    _append_equity_curve(state_path.parent / "alpaca_equity_curve.json", state)
    return state


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _append_equity_curve(curve_path: Path, state: dict) -> None:
    """Persistent equity curve — only grows."""
    curve = {"snapshots": []}
    if curve_path.exists():
        try:
            curve = json.loads(curve_path.read_text())
        except Exception:
            pass
    snap = {
        "timestamp": state.get("last_run"),
        "equity": state.get("account", {}).get("equity"),
        "cash": state.get("account", {}).get("cash"),
        "n_positions": len(state.get("positions", [])),
        "orders_today": len(state.get("orders_placed", [])),
    }
    curve.setdefault("snapshots", []).append(snap)
    curve["snapshots"] = curve["snapshots"][-5000:]
    curve_path.parent.mkdir(parents=True, exist_ok=True)
    curve_path.write_text(json.dumps(curve, indent=2, default=str))



================================================
FILE: silmaril/execution/detail.py
================================================
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



================================================
FILE: silmaril/handoff/__init__.py
================================================
"""silmaril.handoff package."""



================================================
FILE: silmaril/handoff/blocks.py
================================================
[Binary file]


================================================
FILE: silmaril/handoff/brokers.py
================================================
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



================================================
FILE: silmaril/handoff/deeplinks.py
================================================
"""
silmaril.handoff.deeplinks — One-click LLM handoffs.

Each supported LLM gets a deep-link builder. Where the LLM supports
pre-filling a prompt via URL parameter, we use that. Where it doesn't,
we emit a clipboard-copy + open-in-tab pattern (handled on the frontend).

The frontend reads each link's `strategy`:
  "url_param"    → clicking opens the URL directly with prompt pre-loaded
  "copy_and_go"  → clicking copies prompt to clipboard, then opens the URL

All supported LLMs are the user's own account. SILMARIL neither hosts
nor proxies any LLM call. Privacy is simple: we never see the prompt
leave the user's browser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from urllib.parse import quote


@dataclass
class Handoff:
    """One LLM handoff option for a single Handoff Block."""
    llm: str                # "chatgpt" | "claude" | "gemini" | "perplexity" | "grok"
    display_name: str       # "ChatGPT", "Claude", etc.
    icon: str               # path to icon file (served from assets/icons/)
    url: str                # the target URL
    strategy: str           # "url_param" or "copy_and_go"

    def to_dict(self) -> Dict[str, str]:
        return {
            "llm": self.llm,
            "display_name": self.display_name,
            "icon": self.icon,
            "url": self.url,
            "strategy": self.strategy,
        }


def build_handoffs(prompt: str) -> List[Dict[str, str]]:
    """
    Build the full set of deep-links for a given prompt.

    Strategy field tells the frontend whether the LLM accepts a URL-param
    pre-fill (instant) or whether the user must paste from clipboard.
    """
    encoded = quote(prompt)

    handoffs: List[Handoff] = [
        # ── Tier 1: full URL pre-fill ────────────────────────────
        Handoff(
            llm="chatgpt", display_name="ChatGPT",
            icon="assets/icons/chatgpt.svg",
            url=f"https://chatgpt.com/?q={encoded}",
            strategy="url_param",
        ),
        Handoff(
            llm="perplexity", display_name="Perplexity",
            icon="assets/icons/perplexity.svg",
            url=f"https://www.perplexity.ai/?q={encoded}",
            strategy="url_param",
        ),
        Handoff(
            llm="grok", display_name="Grok",
            icon="assets/icons/grok.svg",
            url=f"https://x.com/i/grok?text={encoded}",
            strategy="url_param",
        ),
        Handoff(
            llm="duckai", display_name="DuckDuckGo AI",
            icon="assets/icons/duckai.svg",
            url=f"https://duckduckgo.com/?q={encoded}&ia=chat",
            strategy="url_param",
        ),

        # ── Tier 2: copy-and-go (open homepage, paste from clipboard) ─
        Handoff(
            llm="claude", display_name="Claude",
            icon="assets/icons/claude.svg",
            url="https://claude.ai/new",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="gemini", display_name="Gemini",
            icon="assets/icons/gemini.svg",
            url="https://gemini.google.com/app",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="copilot", display_name="Copilot",
            icon="assets/icons/copilot.svg",
            url="https://copilot.microsoft.com/",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="meta_ai", display_name="Meta AI",
            icon="assets/icons/meta.svg",
            url="https://www.meta.ai/",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="mistral", display_name="Le Chat",
            icon="assets/icons/mistral.svg",
            url="https://chat.mistral.ai/chat",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="deepseek", display_name="DeepSeek",
            icon="assets/icons/deepseek.svg",
            url="https://chat.deepseek.com/",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="qwen", display_name="Qwen",
            icon="assets/icons/qwen.svg",
            url="https://chat.qwen.ai/",
            strategy="copy_and_go",
        ),
        Handoff(
            llm="kimi", display_name="Kimi",
            icon="assets/icons/kimi.svg",
            url="https://www.kimi.com/",
            strategy="copy_and_go",
        ),
    ]
    return [h.to_dict() for h in handoffs]



================================================
FILE: silmaril/handoff/multi_llm_consensus.py
================================================
"""Manual multi-LLM consensus prompt builders for SILMARIL v2.

Design contract
---------------
1. Zero API calls. Every function returns a string.
2. Self-contained prompts. The external LLM sees the asset, the
   cohort, the indicators -- everything it needs to render a useful
   second opinion in one shot.
3. Token-conscious. We trim cohort detail to what matters and skip
   indicators that don't apply to the asset class.
4. Variants are short. Four flavors, each ~600-1200 tokens, so even
   free-tier daily limits don't bite.

Usage from the dashboard
------------------------
The user clicks a "Get second opinion" button on a verdict tile.
The frontend calls the appropriate builder, copies the result to
the clipboard, and the user pastes it into ChatGPT / Gemini / Grok
/ a fresh Claude tab. They paste the response back into the log
note. Done.

Variants
--------
- consensus  : "Rate the cohort's reasoning. Flag what they missed."
- red_team   : "Argue against this verdict. What's the bear case?"
- catalyst   : "Which upcoming catalyst most threatens the verdict?"
- summary    : "One-paragraph plain-English summary."
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

PROMPT_VARIANTS = ("consensus", "red_team", "catalyst", "summary")

# ----------------------------------------------------------------------
# Internal formatters
# ----------------------------------------------------------------------

_SIGNAL_MARKERS = {
    "STRONG_BUY": "++",
    "BUY": "+ ",
    "HOLD": ". ",
    "ABSTAIN": ". ",
    "SELL": "- ",
    "STRONG_SELL": "--",
}


def _fmt_pct(x, digits: int = 2) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{float(x) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_num(x, digits: int = 2) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{float(x):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _format_cohort(verdicts: Iterable[dict]) -> str:
    """Render the agent verdicts as compact rows, no leading indent."""
    rows = []
    for v in verdicts:
        agent = v.get("agent", "?")
        signal = v.get("signal", "HOLD")
        marker = _SIGNAL_MARKERS.get(signal, "??")
        conv = v.get("conviction", 0.0)
        rat = (v.get("rationale") or "").strip().replace("\n", " ")
        if len(rat) > 140:
            rat = rat[:137] + "..."
        rows.append(f"  [{marker}] {agent:<14} conv={conv:.2f}  {rat}")
    return "\n".join(rows) if rows else "  (no verdicts)"


def _format_indicators(market_state: dict, asset_class: str) -> str:
    """Render the technical/macro snapshot, trimmed by asset class."""
    if not market_state:
        return "  (no indicators provided)"

    lines: list[str] = []

    def add(label: str, key: str, formatter=_fmt_num):
        if key in market_state and market_state[key] is not None:
            lines.append(f"  {label:<22} {formatter(market_state[key])}")

    add("price", "price")
    add("SMA20", "sma20")
    add("SMA50", "sma50")
    add("SMA200", "sma200")
    add("RSI(14)", "rsi14")
    add("ATR(14)", "atr14")
    add("Bollinger width", "bb_width", _fmt_pct)
    add("MACD histogram", "macd_hist")
    add("20d momentum", "momentum_20d", _fmt_pct)
    add("20d volatility", "volatility_20d", _fmt_pct)

    if asset_class in {"equity", "etf"}:
        add("VIX", "vix")
        add("10Y yield", "tnx", _fmt_pct)
        add("SPY 20d momentum", "spy_mom_20d", _fmt_pct)
    elif asset_class == "crypto":
        add("BTC dominance", "btc_dominance", _fmt_pct)
        add("funding rate", "funding_rate", _fmt_pct)
    elif asset_class == "fx":
        add("DXY", "dxy")

    return "\n".join(lines) if lines else "  (no indicators provided)"


def _format_catalysts(catalysts: Iterable[dict] | None) -> str:
    if not catalysts:
        return "  (no upcoming catalysts in window)"
    rows = []
    for c in catalysts:
        date = c.get("date", "?")
        ctype = c.get("type", "?")
        title = (c.get("title") or "").strip()
        if len(title) > 100:
            title = title[:97] + "..."
        rows.append(f"  {date} [{ctype}] {title}")
    return "\n".join(rows)


def _header(ticker: str, asset_class: str, regime: str) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return (
        f"Ticker: {ticker}\n"
        f"Asset class: {asset_class}\n"
        f"Date (UTC): {today}\n"
        f"Detected regime: {regime}\n"
    )


# ----------------------------------------------------------------------
# Public prompt builders
# ----------------------------------------------------------------------

def build_consensus_prompt(
    ticker: str,
    asset_class: str,
    regime: str,
    verdicts: Iterable[dict],
    market_state: dict | None = None,
    catalysts: Iterable[dict] | None = None,
    cohort_signal: str | None = None,
    cohort_score: float | None = None,
) -> str:
    """The 'rate the cohort' prompt -- primary use case."""

    cohort_line = ""
    if cohort_signal:
        cohort_line = f"Cohort verdict: {cohort_signal}"
        if cohort_score is not None:
            cohort_line += f" (composite score {cohort_score:+.2f})"
        cohort_line += "\n"

    parts = [
        "You are reviewing the output of SILMARIL, a multi-agent trading",
        "decision system. Below is the live state of the asset, the verdicts",
        "of every agent in the cohort, and the upcoming catalysts in the",
        "next two weeks. Your job is to rate the cohort's collective",
        "reasoning and tell us what they missed.",
        "",
        "Be concise. Be honest. We don't want a hedge-everything answer.",
        "",
        "===== ASSET SNAPSHOT =====",
        _header(ticker, asset_class, regime).rstrip("\n"),
    ]
    if cohort_line:
        parts.append(cohort_line.rstrip("\n"))
    parts += [
        "",
        "===== INDICATORS =====",
        _format_indicators(market_state or {}, asset_class),
        "",
        "===== AGENT COHORT VERDICTS =====",
        "Signal key:  ++ STRONG_BUY   + BUY   . HOLD/ABSTAIN   - SELL   -- STRONG_SELL",
        "",
        _format_cohort(verdicts),
        "",
        "===== UPCOMING CATALYSTS (next ~14 days) =====",
        _format_catalysts(catalysts),
        "",
        "===== YOUR TASK =====",
        "Answer in this exact format:",
        "",
        "1) STRONGEST_AGENT: <name> -- one sentence why their reasoning is the most defensible.",
        "2) WEAKEST_AGENT:   <name> -- one sentence why their reasoning is suspect.",
        "3) MISSING_ANGLE:   <1-3 bullet points> -- things no agent considered.",
        "4) RISK_FLAG:       <a single specific risk to the cohort verdict>.",
        "5) YOUR_CALL:       <STRONG_BUY | BUY | HOLD | SELL | STRONG_SELL> with confidence 0.00-1.00.",
        "6) ONE_LINE_REASON: <one sentence summary of your call>.",
        "",
        "Do not add any text outside this format.",
        "",
    ]
    return "\n".join(parts)


def build_red_team_prompt(
    ticker: str,
    asset_class: str,
    regime: str,
    verdicts: Iterable[dict],
    market_state: dict | None = None,
    catalysts: Iterable[dict] | None = None,
    cohort_signal: str | None = None,
) -> str:
    """The adversarial prompt -- make the LLM argue the other side."""

    cohort_line = f"Cohort verdict: {cohort_signal}" if cohort_signal else ""

    parts = [
        "You are the red team for SILMARIL, a multi-agent trading system.",
        "The cohort below has reached a verdict. Your only job is to argue",
        "against it as strongly and specifically as you can. Do not hedge.",
        "Do not give a balanced view. Find the cracks.",
        "",
        "===== ASSET SNAPSHOT =====",
        _header(ticker, asset_class, regime).rstrip("\n"),
    ]
    if cohort_line:
        parts.append(cohort_line)
    parts += [
        "",
        "===== INDICATORS =====",
        _format_indicators(market_state or {}, asset_class),
        "",
        "===== AGENT COHORT VERDICTS =====",
        _format_cohort(verdicts),
        "",
        "===== UPCOMING CATALYSTS =====",
        _format_catalysts(catalysts),
        "",
        "===== YOUR TASK =====",
        "Build the strongest possible counter-case to the cohort's verdict.",
        "Format:",
        "",
        "1) THESIS_AGAINST: One paragraph (4 sentences max) stating why",
        "   the cohort is wrong.",
        "2) THREE_FACTS:    Three specific data points or facts that",
        "   support the counter-case. Cite from the indicator snapshot",
        "   or catalyst list above when possible.",
        "3) WHAT_WOULD_PROVE_YOU_RIGHT: One concrete observable that, if",
        "   it happened in the next 5 trading days, would confirm the",
        "   counter-case.",
        "4) WHAT_WOULD_PROVE_YOU_WRONG: One observable that would kill",
        "   the counter-case.",
        "",
        "Do not add text outside this format.",
        "",
    ]
    return "\n".join(parts)


def build_catalyst_review_prompt(
    ticker: str,
    asset_class: str,
    catalysts: Iterable[dict],
    cohort_signal: str | None = None,
) -> str:
    """Catalyst-focused review -- which event most threatens the verdict."""

    cat_list = list(catalysts)
    if not cat_list:
        return (
            f"No upcoming catalysts found for {ticker} in the next 14 days.\n"
            f"Cohort verdict: {cohort_signal or 'unspecified'}.\n"
            "Question: is there a known event in the wider market in the next\n"
            "two weeks that should make us reconsider this verdict?\n"
            "Answer in 3 sentences max.\n"
        )

    cohort_line = f"Cohort verdict: {cohort_signal}" if cohort_signal else ""
    parts = [
        f"Review the upcoming catalysts for {ticker} ({asset_class}) and rank",
        "them by how strongly each could invalidate the cohort verdict.",
        "Be specific.",
        "",
    ]
    if cohort_line:
        parts.append(cohort_line)
        parts.append("")
    parts += [
        "===== UPCOMING CATALYSTS =====",
        _format_catalysts(cat_list),
        "",
        "===== YOUR TASK =====",
        "Answer in this format:",
        "",
        "1) MOST_DANGEROUS:   <date + event> -- one sentence on why.",
        "2) SECOND_DANGEROUS: <date + event> -- one sentence on why.",
        "3) IGNORE:           <date + event or 'none'> -- events the",
        "   cohort can safely disregard.",
        "4) HEDGE_IDEA:       One concrete way to hedge against the most",
        "   dangerous event without exiting the position.",
        "",
        "Do not add text outside this format.",
        "",
    ]
    return "\n".join(parts)


def build_summary_prompt(
    ticker: str,
    asset_class: str,
    regime: str,
    verdicts: Iterable[dict],
    cohort_signal: str | None = None,
    cohort_score: float | None = None,
) -> str:
    """Plain-English one-paragraph summary -- cheapest prompt."""

    cohort_line = ""
    if cohort_signal:
        cohort_line = f"Cohort verdict: {cohort_signal}"
        if cohort_score is not None:
            cohort_line += f" (composite score {cohort_score:+.2f})"

    parts = [
        "Translate this trading decision into one paragraph a smart",
        "non-trader could understand. No jargon. No bullet points. No",
        "disclaimers. 4-5 sentences.",
        "",
        "===== INPUT =====",
        _header(ticker, asset_class, regime).rstrip("\n"),
    ]
    if cohort_line:
        parts.append(cohort_line)
    parts += [
        "",
        "Agents that voted:",
        _format_cohort(verdicts),
        "",
        "Write the paragraph now.",
        "",
    ]
    return "\n".join(parts)


# ----------------------------------------------------------------------
# Self-check
# ----------------------------------------------------------------------

if __name__ == "__main__":
    sample_verdicts = [
        {
            "agent": "AEGIS",
            "signal": "BUY",
            "conviction": 0.72,
            "rationale": "Price above all three SMAs, RSI 58, bullish MACD cross last week.",
        },
        {
            "agent": "FORGE",
            "signal": "BUY",
            "conviction": 0.65,
            "rationale": "Breakout above 50-day high on rising volume.",
        },
        {
            "agent": "KESTREL+",
            "signal": "ABSTAIN",
            "conviction": 0.0,
            "rationale": "Hurst 0.58 - trender, mean-reversion logic does not apply.",
        },
        {
            "agent": "ATLAS",
            "signal": "HOLD",
            "conviction": 0.4,
            "rationale": "Macro neutral, VIX 18, 10Y stable. No tilt.",
        },
    ]
    sample_state = {
        "price": 432.10,
        "sma20": 425.0,
        "sma50": 418.0,
        "sma200": 401.0,
        "rsi14": 58.2,
        "atr14": 6.4,
        "bb_width": 0.034,
        "macd_hist": 1.2,
        "momentum_20d": 0.041,
        "volatility_20d": 0.011,
        "vix": 18.1,
        "tnx": 0.0421,
        "spy_mom_20d": 0.025,
    }
    sample_cats = [
        {"date": "2026-05-01", "type": "earnings", "title": "Q1 earnings, AMC, consensus EPS $2.18"},
        {"date": "2026-05-07", "type": "fomc", "title": "FOMC rate decision"},
        {"date": "2026-05-15", "type": "opex", "title": "Monthly options expiration"},
    ]

    for variant in PROMPT_VARIANTS:
        print(f"\n{'=' * 60}")
        print(f"VARIANT: {variant}")
        print(f"{'=' * 60}\n")
        if variant == "consensus":
            print(build_consensus_prompt("SPY", "etf", "BULL", sample_verdicts,
                                         sample_state, sample_cats, "BUY", 0.62))
        elif variant == "red_team":
            print(build_red_team_prompt("SPY", "etf", "BULL", sample_verdicts,
                                        sample_state, sample_cats, "BUY"))
        elif variant == "catalyst":
            print(build_catalyst_review_prompt("SPY", "etf", sample_cats, "BUY"))
        elif variant == "summary":
            print(build_summary_prompt("SPY", "etf", "BULL", sample_verdicts, "BUY", 0.62))



================================================
FILE: silmaril/ingestion/__init__.py
================================================
"""silmaril.ingestion package."""



================================================
