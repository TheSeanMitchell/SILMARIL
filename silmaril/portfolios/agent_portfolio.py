"""
silmaril.portfolios.agent_portfolio — Per-agent $10K paper portfolios.

Per Alpha 2.0: every strategist agent gets a portfolio, even silent ones.
The `ensure_all_agents_have_portfolios` function makes this idempotent.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


STARTING_EQUITY = 10000.0


@dataclass
class AgentPortfolio:
    agent: str
    starting_equity: float = STARTING_EQUITY
    current_equity: float = STARTING_EQUITY
    cash: float = STARTING_EQUITY
    current_position: Optional[Dict] = None
    history: List[Dict] = field(default_factory=list)
    equity_curve: List[Dict] = field(default_factory=list)
    inception_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).date().isoformat()
    )

    @property
    def total_return_pct(self) -> float:
        if self.starting_equity == 0:
            return 0.0
        return (self.current_equity - self.starting_equity) / self.starting_equity

    def total_equity(self, mark_price: Optional[float] = None) -> float:
        """Return total equity: cash + mark-to-market value of current position."""
        if self.current_position is None:
            return self.cash
        qty = self.current_position.get("qty", 0) or 0
        price = mark_price if mark_price is not None else self.current_position.get("entry_price", 0)
        position_value = qty * (price or 0)
        return self.cash + position_value

    def open_position(self, ticker: str, qty: float, entry_price: float, signal: str) -> None:
        cost = qty * entry_price
        if cost > self.cash:
            return
        self.cash -= cost
        self.current_position = {
            "ticker": ticker,
            "qty": qty,
            "entry_price": entry_price,
            "signal": signal,
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }
        self.history.append({
            "action": "OPEN",
            "ticker": ticker,
            "qty": qty,
            "price": entry_price,
            "signal": signal,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def close_position(self, exit_price: float) -> Optional[float]:
        if not self.current_position:
            return None
        qty = self.current_position["qty"]
        entry = self.current_position["entry_price"]
        signal = self.current_position.get("signal", "BUY")
        if signal in ("SELL", "STRONG_SELL"):
            pnl = (entry - exit_price) * qty  # short
        else:
            pnl = (exit_price - entry) * qty  # long
        proceeds = qty * exit_price if signal not in ("SELL", "STRONG_SELL") else qty * entry + pnl
        self.cash += proceeds
        self.current_equity = self.cash
        ticker = self.current_position["ticker"]
        self.history.append({
            "action": "CLOSE",
            "ticker": ticker,
            "qty": qty,
            "price": exit_price,
            "pnl": pnl,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.current_position = None
        return pnl

    def snapshot_equity(self) -> None:
        self.equity_curve.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "equity": self.current_equity,
            "cash": self.cash,
            "in_position": self.current_position is not None,
        })
        self.equity_curve = self.equity_curve[-2000:]

    def to_dict(self) -> Dict:
        return asdict(self)


def agent_portfolio_act(
    portfolio: AgentPortfolio,
    debate_dicts: List[Dict],
    prices: Dict[str, float],
) -> AgentPortfolio:
    """
    Run one cycle of portfolio management for a single agent.

    Logic:
      1. If holding a position, check whether the latest consensus flipped
         to SELL/STRONG_SELL — if so, close it.
      2. If flat (or just closed), find the best BUY-consensus debate for
         this agent and open a 10% position.

    Returns the mutated portfolio.
    """
    today = datetime.now(timezone.utc).date().isoformat()
    agent = portfolio.agent

    # ── Step 1: Evaluate existing position ──────────────────────
    if portfolio.current_position:
        held_ticker = portfolio.current_position["ticker"]
        current_price = prices.get(held_ticker)

        # Mark-to-market equity update
        if current_price:
            qty = portfolio.current_position.get("qty", 0) or 0
            portfolio.current_equity = portfolio.cash + qty * current_price

        # Check if consensus on the held ticker has turned negative
        held_debate = next(
            (d for d in debate_dicts if d.get("ticker") == held_ticker), None
        )
        if held_debate:
            cons_signal = held_debate.get("consensus", {}).get("signal", "HOLD")
            if cons_signal in ("SELL", "STRONG_SELL") and current_price:
                portfolio.close_position(current_price)
                portfolio.history.append({
                    "action": "HOLD",
                    "date": today,
                    "reason": f"Closed {held_ticker} — consensus flipped to {cons_signal}",
                    "equity": round(portfolio.total_equity(), 2),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                return portfolio

        # Still holding — log HOLD and return
        portfolio.history.append({
            "action": "HOLD",
            "date": today,
            "ticker": held_ticker,
            "equity": round(portfolio.total_equity(current_price), 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return portfolio

    # ── Step 2: Find the best BUY for this agent ─────────────────
    # Look for debates where this agent voted BUY/STRONG_BUY
    best_debate = None
    best_score = -999.0
    for d in debate_dicts:
        # Check if this agent voted BUY/STRONG_BUY in this debate
        verdicts = d.get("verdicts", [])
        agent_vote = next(
            (v for v in verdicts if v.get("agent") == agent and
             v.get("signal") in ("BUY", "STRONG_BUY") and
             not v.get("is_specialist")),
            None,
        )
        if agent_vote is None:
            continue
        # Also require consensus to be at least neutral
        cons_signal = d.get("consensus", {}).get("signal", "HOLD")
        if cons_signal in ("SELL", "STRONG_SELL"):
            continue
        score = d.get("consensus", {}).get("score", 0) or 0
        if score > best_score:
            best_score = score
            best_debate = d

    if best_debate is None:
        portfolio.history.append({
            "action": "HOLD",
            "date": today,
            "reason": "No qualifying BUY signal found for this agent",
            "equity": round(portfolio.total_equity(), 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return portfolio

    ticker = best_debate["ticker"]
    entry_price = prices.get(ticker)
    if not entry_price or entry_price <= 0:
        portfolio.history.append({
            "action": "HOLD",
            "date": today,
            "reason": f"No price available for {ticker}",
            "equity": round(portfolio.total_equity(), 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return portfolio

    # Size: 10% of total equity, capped so we don't overspend cash
    position_value = min(portfolio.total_equity() * 0.10, portfolio.cash * 0.95)
    if position_value < 1.0:
        return portfolio

    qty = position_value / entry_price
    portfolio.open_position(ticker, qty, entry_price, "BUY")
    portfolio.current_equity = portfolio.total_equity(entry_price)

    return portfolio


def load_portfolios(path: Path) -> Dict[str, AgentPortfolio]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return {}
    out = {}
    known = set(AgentPortfolio.__dataclass_fields__.keys())
    for agent, data in raw.items():
        clean = {k: v for k, v in data.items() if k in known}
        out[agent] = AgentPortfolio(**clean)
    return out


def save_portfolios(
    path: Path,
    portfolios: Dict[str, AgentPortfolio],
    prices: Optional[Dict[str, float]] = None,
) -> None:
    """Persist portfolios. `prices` is accepted for mark-to-market but optional."""
    if prices:
        for p in portfolios.values():
            if p.current_position:
                mark = prices.get(p.current_position.get("ticker", ""))
                if mark:
                    qty = p.current_position.get("qty", 0) or 0
                    p.current_equity = p.cash + qty * mark

    out = {agent: asdict(p) for agent, p in portfolios.items()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str))


def ensure_all_agents_have_portfolios(
    portfolios: Dict[str, AgentPortfolio],
    all_agent_names: List[str],
) -> Dict[str, AgentPortfolio]:
    """Idempotent — creates a $10K portfolio for any agent without one."""
    for name in all_agent_names:
        if name not in portfolios:
            portfolios[name] = AgentPortfolio(agent=name)
    return portfolios
