"""
silmaril.portfolios.agent_portfolio — Per-agent $10K career portfolios.

Each of the 15 main voting agents runs their own persistent $10K book.
Daily flow:

  1. Each agent considers all assets in the universe and produces verdicts
     (this already happens during the main debate)
  2. From their own verdicts, each agent picks their single highest-
     conviction BUY/STRONG_BUY (within their specialty universe)
  3. If they're already holding something, they sell it first (full fees)
     and buy the new pick. If their pick is the same, they HODL.
  4. If no BUY-side conviction (only HOLDs/SELLs/abstentions), they
     stay in cash for the day and log the choice
  5. Equity curve, P&L, fees, and full execution receipt all logged

This is pure simulation. No real money. Every action persisted to
agent_portfolios.json so the dashboard can render an equity curve and
agent-card track record.

Why this matters: the main debate produces *consensus*; per-agent
portfolios produce *individual track record*. Without individual
track records, we can never weight agents by performance (Phase C).
This file is the foundation for the learning loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..execution.detail import build_execution
import math as _math
def _sanitize_json(obj):
    """Recursively convert NaN/Inf to None for valid JSON output."""
    if isinstance(obj, float):
        if _math.isnan(obj) or _math.isinf(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json(v) for v in obj]
    return obj


STARTING_CAPITAL = 10_000.00


@dataclass
class AgentPortfolio:
    """One agent's persistent $10K book."""
    agent: str
    balance: float = STARTING_CAPITAL          # cash
    current_position: Optional[Dict] = None    # {ticker, shares, entry_price, ...}
    equity_curve: List[Dict] = field(default_factory=list)  # [{date, equity}, ...]
    history: List[Dict] = field(default_factory=list)       # full action log
    inception_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat()
    )
    realized_pnl: float = 0.0
    total_fees_paid: float = 0.0
    trades_count: int = 0

    def total_equity(self, mark_price: Optional[float] = None) -> float:
        """Cash + market value of any open position."""
        if self.current_position and mark_price is not None:
            return self.balance + self.current_position["shares"] * mark_price
        if self.current_position:
            # Fall back to entry price if we lack a mark
            return self.balance + (
                self.current_position["shares"] * self.current_position["entry_price"]
            )
        return self.balance

    def to_dict(self, prices: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        prices = prices or {}
        mark = None
        if self.current_position:
            mark = prices.get(self.current_position["ticker"])
        equity = self.total_equity(mark)
        unrealized = 0.0
        if self.current_position and mark is not None:
            unrealized = (mark - self.current_position["entry_price"]) * self.current_position["shares"]

        return {
            "agent": self.agent,
            "balance": round(self.balance, 4),
            "current_position": self.current_position,
            "equity": round(equity, 4),
            "unrealized_pnl": round(unrealized, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "total_fees_paid": round(self.total_fees_paid, 4),
            "trades_count": self.trades_count,
            "return_pct": round((equity / STARTING_CAPITAL - 1) * 100, 3),
            "equity_curve": self.equity_curve[-90:],  # cap so file doesn't balloon
            "recent_history": self.history[-30:],
            "inception_date": self.inception_date,
        }


def _verdicts_to_pick(
    agent_codename: str,
    verdicts_by_ticker: Dict[str, Dict],
) -> Optional[Dict]:
    """
    Find this agent's highest-conviction BUY across all assets.
    Returns the {ticker, signal, conviction, rationale, price} dict or None.
    """
    candidates = []
    for ticker, vmap in verdicts_by_ticker.items():
        v = vmap.get(agent_codename)
        if not v:
            continue
        if v["signal"] in ("BUY", "STRONG_BUY"):
            candidates.append({**v, "ticker": ticker})
    if not candidates:
        return None
    candidates.sort(key=lambda v: (
        2 if v["signal"] == "STRONG_BUY" else 1,
        v["conviction"],
    ), reverse=True)
    return candidates[0]


def agent_portfolio_act(
    portfolio: AgentPortfolio,
    debate_dicts: List[Dict],
    prices: Dict[str, float],
) -> AgentPortfolio:
    """
    Run one day for one agent. Pure function over (state, today's debate)
    that returns the updated state. Idempotent on the same date.
    """
    today = datetime.now(timezone.utc).date().isoformat()

    # Already acted today? skip — keeps reruns idempotent
    if portfolio.history and portfolio.history[-1].get("date") == today:
        # Refresh the equity curve mark for today using current prices
        mark = None
        if portfolio.current_position:
            mark = prices.get(portfolio.current_position["ticker"])
        equity = portfolio.total_equity(mark)
        if portfolio.equity_curve and portfolio.equity_curve[-1].get("date") == today:
            portfolio.equity_curve[-1]["equity"] = round(equity, 4)
        return portfolio

    # Build a quick lookup of this agent's verdicts by ticker
    verdicts_by_ticker: Dict[str, Dict] = {}
    for d in debate_dicts:
        for v in d.get("verdicts", []):
            verdicts_by_ticker.setdefault(d["ticker"], {})[v["agent"]] = v
            verdicts_by_ticker[d["ticker"]][v["agent"]]["price"] = d.get("price")

    # Find best buy-side pick
    pick = _verdicts_to_pick(portfolio.agent, verdicts_by_ticker)

    held_ticker = portfolio.current_position["ticker"] if portfolio.current_position else None
    target_ticker = pick["ticker"] if pick else None
    target_price = prices.get(target_ticker) if target_ticker else None

    asset_class_for = lambda t: "crypto" if t.endswith("-USD") else "etf" if t in {
        "SPY","QQQ","IWM","DIA","VTI","XLK","XLE","XLF","XLV","XLP","XLY","XLI","XLB","XLU","XLRE",
        "GLD","IAU","SLV","SIVR","PPLT","PALL","TLT","IEF","SHY","HYG","LQD","UUP","FXE","FXY","FXF",
        "SMH","IGV","ARKK","DBC","USO","UNG","CPER",
    } else "equity"

    # ── Case 1: same ticker → HODL, mark equity ──────────────────
    if held_ticker and target_ticker == held_ticker:
        mark = prices.get(held_ticker, portfolio.current_position["entry_price"])
        equity = portfolio.total_equity(mark)
        portfolio.history.append({
            "date": today,
            "action": "HOLD",
            "ticker": held_ticker,
            "reason": (
                f"{portfolio.agent} still likes {held_ticker} as their top BUY. "
                f"No rotation, no fees."
            ),
            "equity": round(equity, 4),
        })
        portfolio.equity_curve.append({"date": today, "equity": round(equity, 4)})
        return portfolio

    # ── Case 2: no buy-side pick AND we're flat → cash day ─────
    if not pick and not held_ticker:
        equity = portfolio.balance
        portfolio.history.append({
            "date": today,
            "action": "CASH",
            "reason": (
                f"{portfolio.agent} sees no BUY setups in their specialty today. "
                f"Sitting in cash."
            ),
            "equity": round(equity, 4),
        })
        portfolio.equity_curve.append({"date": today, "equity": round(equity, 4)})
        return portfolio

    # ── Case 3: holding something but no new pick → close out ──
    if held_ticker and not pick:
        _close_position(portfolio, prices, today, asset_class_for)
        equity = portfolio.balance
        portfolio.equity_curve.append({"date": today, "equity": round(equity, 4)})
        return portfolio

    # ── Case 4: rotating into a new ticker ──────────────────────
    if held_ticker and target_ticker and held_ticker != target_ticker:
        _close_position(portfolio, prices, today, asset_class_for)

    # Now buy the target
    if target_ticker and target_price:
        _open_position(
            portfolio, target_ticker, target_price, today, pick, asset_class_for,
        )

    # Mark the equity curve
    mark = prices.get(target_ticker) if target_ticker else None
    equity = portfolio.total_equity(mark)
    portfolio.equity_curve.append({"date": today, "equity": round(equity, 4)})
    return portfolio


def _close_position(portfolio, prices, today, asset_class_for):
    """SELL the current position with full fee accounting."""
    pos = portfolio.current_position
    ticker = pos["ticker"]
    shares = pos["shares"]
    entry_price = pos["entry_price"]
    exit_price = prices.get(ticker, entry_price)

    execution = build_execution(
        ticker=ticker, asset_class=asset_class_for(ticker), side="SELL",
        shares=shares, price=exit_price,
        available_before=portfolio.balance,
    )
    proceeds = execution["net_proceeds"] or (shares * exit_price)
    pnl = proceeds - (shares * entry_price)
    pnl_pct = ((exit_price / entry_price) - 1) * 100 if entry_price else 0.0

    portfolio.balance += proceeds
    portfolio.realized_pnl += pnl
    portfolio.total_fees_paid += execution["fees"]["total"]
    portfolio.trades_count += 1
    portfolio.history.append({
        "date": today,
        "action": "SELL",
        "ticker": ticker,
        "shares": round(shares, 6),
        "entry_price": round(entry_price, 4),
        "exit_price": round(exit_price, 4),
        "proceeds": round(proceeds, 4),
        "pnl": round(pnl, 4),
        "pnl_pct": round(pnl_pct, 2),
        "balance_after": round(portfolio.balance, 4),
        "execution": execution,
    })
    portfolio.current_position = None


def _open_position(portfolio, ticker, price, today, pick, asset_class_for):
    """BUY the new target with full fee accounting."""
    available = portfolio.balance
    # Fit shares so cost + fees ≤ balance
    shares = available / price
    for _ in range(3):
        test_exec = build_execution(
            ticker=ticker, asset_class=asset_class_for(ticker), side="BUY",
            shares=shares, price=price, available_before=available,
        )
        over = (test_exec["net_cost"] or 0) - available
        if over <= 0.001:
            break
        shares -= (over / price) * 1.01

    execution = build_execution(
        ticker=ticker, asset_class=asset_class_for(ticker), side="BUY",
        shares=shares, price=price, available_before=available,
    )
    cost = execution["net_cost"] or (shares * price)

    portfolio.current_position = {
        "ticker": ticker,
        "shares": round(shares, 6),
        "entry_price": round(price, 4),
        "entry_date": today,
        "thesis": pick.get("rationale", "")[:240],
        "execution": execution,
    }
    portfolio.balance -= cost
    portfolio.total_fees_paid += execution["fees"]["total"]
    portfolio.trades_count += 1
    portfolio.history.append({
        "date": today,
        "action": "BUY",
        "ticker": ticker,
        "shares": round(shares, 6),
        "entry_price": round(price, 4),
        "cost": round(cost, 4),
        "balance_after": round(portfolio.balance, 4),
        "execution": execution,
        "thesis": pick.get("rationale", "")[:240],
    })


def load_portfolios(path) -> Dict[str, AgentPortfolio]:
    """Load all agent portfolios from a single JSON file."""
    import json
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
    except Exception:
        return {}
    out = {}
    for agent_name, payload in data.get("portfolios", {}).items():
        out[agent_name] = AgentPortfolio(
            agent=agent_name,
            balance=payload.get("balance", STARTING_CAPITAL),
            current_position=payload.get("current_position"),
            equity_curve=payload.get("equity_curve", []),
            history=payload.get("history", []),
            inception_date=payload.get("inception_date", datetime.now(timezone.utc).date().isoformat()),
            realized_pnl=payload.get("realized_pnl", 0.0),
            total_fees_paid=payload.get("total_fees_paid", 0.0),
            trades_count=payload.get("trades_count", 0),
        )
    return out


def save_portfolios(path, portfolios: Dict[str, AgentPortfolio], prices: Dict[str, float]) -> None:
    """Persist all agent portfolios to a single JSON file."""
    import json
    from pathlib import Path
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "starting_capital": STARTING_CAPITAL,
        "portfolios": {
            name: _serialize_full(p) for name, p in portfolios.items()
        },
        "summary": _build_summary(portfolios, prices),
    }
    Path(path).write_text(json.dumps(_sanitize_json(payload), indent=2, default=str, allow_nan=False))


def _serialize_full(p: AgentPortfolio) -> Dict[str, Any]:
    """Full serialization (vs to_dict which trims for the dashboard)."""
    return {
        "agent": p.agent,
        "balance": round(p.balance, 4),
        "current_position": p.current_position,
        "equity_curve": p.equity_curve,
        "history": p.history,
        "inception_date": p.inception_date,
        "realized_pnl": round(p.realized_pnl, 4),
        "total_fees_paid": round(p.total_fees_paid, 4),
        "trades_count": p.trades_count,
    }


def _build_summary(portfolios: Dict[str, AgentPortfolio], prices: Dict[str, float]) -> Dict[str, Any]:
    """Aggregate stats across the cohort for the dashboard leaderboard."""
    rows = []
    for name, p in portfolios.items():
        mark = None
        if p.current_position:
            mark = prices.get(p.current_position["ticker"])
        equity = p.total_equity(mark)
        rows.append({
            "agent": name,
            "equity": round(equity, 4),
            "return_pct": round((equity / STARTING_CAPITAL - 1) * 100, 3),
            "realized_pnl": round(p.realized_pnl, 4),
            "trades_count": p.trades_count,
            "fees_paid": round(p.total_fees_paid, 4),
        })
    rows.sort(key=lambda r: r["equity"], reverse=True)
    return {
        "leaderboard": rows,
        "best": rows[0] if rows else None,
        "worst": rows[-1] if rows else None,
        "cohort_avg_return_pct": round(
            sum(r["return_pct"] for r in rows) / len(rows), 3
        ) if rows else 0.0,
    }
