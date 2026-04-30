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
        self.current_equity = self.cash  # mark-to-market simplified
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


def load_portfolios(path: Path) -> Dict[str, AgentPortfolio]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except Exception:
        return {}
    out = {}
    known = {f.name for f in AgentPortfolio.__dataclass_fields__.values()}
    for agent, data in raw.items():
        clean = {k: v for k, v in data.items() if k in known}
        out[agent] = AgentPortfolio(**clean)
    return out


def save_portfolios(path: Path, portfolios: Dict[str, AgentPortfolio]) -> None:
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
