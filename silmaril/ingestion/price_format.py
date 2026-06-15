"""Price formatting for sub-penny tokens. Fixes JRR Token $0.0000 bug."""
from __future__ import annotations
from typing import Optional

def price_decimals(price: Optional[float]) -> int:
    if price is None or price <= 0: return 4
    if price < 0.001: return 8
    if price < 0.01:  return 6
    if price < 1.0:   return 4
    return 2

def format_price(price: Optional[float], ticker: str = "") -> str:
    if price is None or price <= 0: return "N/A"
    return f"${price:.{price_decimals(price)}f}"

def safe_price(price: Optional[float], ticker: str = "", min_price: float = 1e-12) -> Optional[float]:
    if price is None: return None
    if price <= 0 or price < min_price:
        if ticker:
            print(f"[price] WARNING: {ticker} price {price} invalid")
        return None
    return price

def round_price(price: float, ticker: str = "") -> float:
    if price is None or price <= 0: return 0.0
    return round(price, price_decimals(price))
