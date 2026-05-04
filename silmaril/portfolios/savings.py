"""silmaril.portfolios.savings — Profit-harvest accounting.

Every winning close above the principal target sweeps excess
to a savings ledger. Cash resets to the principal so the trader
starts each new round with the same capital. Losses come out
of trading capital — savings only grows.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def harvest_to_savings(portfolio: Any, principal_target: float) -> float:
    """Sweep cash > principal_target into savings. Returns harvested amount."""
    cash = getattr(portfolio, "cash", 0) or 0
    if cash <= principal_target:
        return 0.0
    harvested = cash - principal_target
    if not hasattr(portfolio, "savings") or portfolio.savings is None:
        portfolio.savings = 0.0
    portfolio.savings = float(portfolio.savings) + harvested
    portfolio.cash = principal_target
    # Log harvest in history if available
    if hasattr(portfolio, "history") and isinstance(portfolio.history, list):
        now = datetime.now(timezone.utc)
        portfolio.history.append({
            "date": now.date().isoformat(),
            "timestamp": now.isoformat(),
            "action": "HARVEST",
            "amount": round(harvested, 4),
            "savings_total": round(portfolio.savings, 4),
            "principal_target": principal_target,
            "reason": f"Cash exceeded principal — pocketed ${harvested:.2f}",
        })
    return harvested


def lifetime_value(portfolio: Any, mark_price: Optional[float] = None) -> Dict[str, float]:
    """Total value: cash + savings + open MTM."""
    cash = float(getattr(portfolio, "cash", 0) or 0)
    savings = float(getattr(portfolio, "savings", 0) or 0)
    open_value = 0.0
    pos = getattr(portfolio, "current_position", None)
    if pos:
        qty = pos.get("qty", 0) or 0
        price = mark_price if mark_price is not None else pos.get("entry_price", 0)
        open_value = qty * (price or 0)
    return {
        "cash": round(cash, 4),
        "savings": round(savings, 4),
        "open_value": round(open_value, 4),
        "total": round(cash + savings + open_value, 4),
    }
