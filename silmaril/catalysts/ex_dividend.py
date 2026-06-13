"""
silmaril.catalysts.ex_dividend

Ex-dividend dates. On the ex-div date, a stock's price drops by approximately
the dividend amount. This is mechanical and predictable. There are nuances
(qualified dividend tax, currency, etc.) but the price gap on ex-day is real.

Source: yfinance.Ticker(symbol).dividends (free, no auth needed).
We sample a watchlist of dividend-paying stocks (SP500 dividend payers).

Output: list of {date, ticker, type='ex_div', dividend_amount, yield_proxy}.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional


# Dividend-paying watchlist. Tweak in production to match your universe.
DIVIDEND_WATCHLIST = [
    "AAPL", "MSFT", "JNJ", "PG", "KO", "PEP", "JPM", "V", "MA", "WMT",
    "COST", "MCD", "HD", "VZ", "T", "CVX", "XOM", "MMM", "CAT", "GE",
    "IBM", "INTC", "PFE", "MRK", "ABBV", "BMY", "LMT", "RTX", "BA", "BLK",
    "GS", "MS", "AXP", "TGT", "LOW", "DIS", "NKE", "SBUX", "ORCL", "CSCO",
]


def fetch_ex_dividend_calendar(
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    watchlist: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    start_date = start_date or date.today()
    end_date = end_date or (start_date + timedelta(days=30))
    watchlist = watchlist or DIVIDEND_WATCHLIST

    try:
        import yfinance as yf
    except ImportError:
        print("[catalysts] yfinance not installed; ex-div calendar empty")
        return []

    out: List[Dict[str, Any]] = []
    for sym in watchlist:
        try:
            t = yf.Ticker(sym)
            cal = t.calendar  # may have 'Ex-Dividend Date' or be None
            div_history = t.dividends
        except Exception as e:
            print(f"[catalysts] ex-div fetch failed for {sym}: {e}")
            continue

        # Use the calendar field when available
        ex_div_date = None
        last_div_amount = None
        try:
            if cal is not None and hasattr(cal, "get"):
                # yfinance returns a dict-like for newer versions
                ed = cal.get("Ex-Dividend Date") or cal.get("ExDividendDate")
                if ed and hasattr(ed, "date"):
                    ex_div_date = ed.date()
        except Exception:
            pass

        # Fallback: if recent history shows quarterly cadence, project next
        if div_history is not None and len(div_history) >= 2:
            try:
                last_div_amount = float(div_history.iloc[-1])
            except Exception:
                last_div_amount = None

        if ex_div_date is None or not (start_date <= ex_div_date <= end_date):
            continue

        out.append({
            "date": ex_div_date.isoformat(),
            "type": "ex_div",
            "ticker": sym,
            "title": (f"{sym} ex-dividend ${last_div_amount:.3f}"
                     if last_div_amount else f"{sym} ex-dividend"),
            "magnitude": "low",
            "source_url": f"https://finance.yahoo.com/quote/{sym}/history?filter=div",
            "dividend_amount": last_div_amount,
            "watchlist_tags": ["mechanical_gap_down"],
        })

    out.sort(key=lambda c: c["date"])
    return out
